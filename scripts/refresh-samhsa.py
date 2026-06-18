#!/usr/bin/env python3
"""
SAMHSA monthly refresh for gth-mcp-server.

Pipeline:
  1. Fetch SA-only facility data from findtreatment.gov
  2. Normalize to existing facilities.json schema
  3. DEDUP: drop SAMHSA records whose (lat,lng) or (name_norm,state,city) collides with curated
  4. DIFF against committed facilities.json to identify net-new records
     (primary key: rounded lat/lng; fallback: name_norm+state+city)
  5. ENRICH net-new + weak-insurance records via Serper + Claude Haiku 4.5
  6. Write merged facilities.json

Schema fields written for SAMHSA records:
  name, city, state, stateAbbr, types[], insurance[], phone, website,
  description, latitude, longitude, samhsa_verified, curated, featured,
  refreshed_at, enriched_at (optional), enrichment_confidence (optional)

Targeting strategy (added 2026-05-01 after first run found 7852 false net-new):
  - Primary identity key: (round(lat,5), round(lng,5))  — ~1m precision
  - Fallback (when coords missing): (name_norm, state, city)
  - Both dedup vs curated AND diff vs previous use the SAME key strategy

Env vars required:
  ANTHROPIC_API_KEY_LOCAL  - Anthropic API key (LOCAL suffix per CC env convention)
  SERPER_API_KEY           - Serper.dev key for Google search
"""
import json
import os
import re
import sys
import urllib.request
import urllib.parse
import urllib.error
import time
import random
from datetime import date

REFRESHED_AT = date.today().isoformat()
API_BASE = "https://findtreatment.gov/locator/exportsAsJson/v2"
PAGE_SIZE = 1000

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACILITIES_PATH = os.path.join(REPO_ROOT, "facilities.json")

# Enrichment config
ENRICH_MODEL = "claude-haiku-4-5-20251001"
HAIKU_INPUT_PRICE_PER_M = 1.0
HAIKU_OUTPUT_PRICE_PER_M = 5.0
HAIKU_CACHE_WRITE_PRICE_PER_M = 1.25
HAIKU_CACHE_READ_PRICE_PER_M = 0.10
SERPER_PRICE_PER_CREDIT = 0.001
BUDGET_HARD_CAP = 1.50
COORD_PRECISION = 5  # decimal places — ~1.1m at 5dp

INSURANCE_VOCAB = [
    "Most Major Insurance", "Medicare", "Medicaid", "Tricare",
    "Blue Cross", "Aetna", "Cigna", "United Healthcare",
    "Sliding Scale", "Self-Pay",
]

ENRICH_SYSTEM_PROMPT = (
    "You extract addiction-treatment facility info from web search snippets. "
    "Return ONLY valid JSON, no prose, no markdown fence. "
    "GROUNDING RULE: Every claim in `description` must be supported by the search snippets. "
    "DO NOT invent founding dates, success rates, program counts, certifications, or any unverified claim. "
    "If snippets are sparse or off-topic, write a minimal factual description from SAMHSA fields only "
    "(form: 'SAMHSA-sourced facility in {city}, {state}. Services include {types}.')."
)

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico", "VI": "Virgin Islands", "GU": "Guam",
    "AS": "American Samoa", "MP": "Northern Mariana Islands",
}


def fetch_page(page):
    qs = urllib.parse.urlencode({"sType": "sa", "pageSize": PAGE_SIZE, "page": page})
    url = f"{API_BASE}?{qs}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "gth-mcp-refresh/1.0"})
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to fetch page {page}: {last_err}")


def services_lookup(services):
    out = {}
    for s in services or []:
        code = s.get("f2"); val = s.get("f3") or ""
        if code: out[code] = val
    return out


def derive_types(svc):
    types = []
    setting = (svc.get("SET") or "").lower()
    if "hospital inpatient" in setting or "residential" in setting:
        types.append("Inpatient Rehab")
    if "detox" in setting:
        types.append("Detox")
    if "intensive outpatient" in setting or "partial hospitalization" in setting or "day treatment" in setting:
        types.append("IOP (Intensive Outpatient)")
    if "outpatient" in setting and "Outpatient" not in types:
        types.append("Outpatient")
    if svc.get("OM") or svc.get("OT"):
        types.append("MAT (Medication-Assisted Treatment)")
    tap = (svc.get("TAP") or "").lower(); ecs = (svc.get("ECS") or "").lower()
    if "counseling" in tap or "counseling" in ecs:
        types.append("Counseling")
    seen, out = set(), []
    for t in types:
        if t not in seen:
            seen.add(t); out.append(t)
    return out


def derive_insurance(svc):
    pay = (svc.get("PAY") or "").lower()
    out = []
    if "private health insurance" in pay or "commercial" in pay: out.append("Most Major Insurance")
    if "medicare" in pay: out.append("Medicare")
    if "medicaid" in pay: out.append("Medicaid")
    if "tricare" in pay or "military insurance" in pay: out.append("Tricare")
    if "sliding fee" in pay or "sliding scale" in pay: out.append("Sliding Scale")
    if not out: out.append("Contact for details")
    return out


def normalize(row):
    name1 = (row.get("name1") or "").strip()
    name2 = (row.get("name2") or "").strip()
    name = name1 if not name2 else (f"{name1} - {name2}" if name1 else name2)
    name = name or "Unknown Facility"
    state_abbr = (row.get("state") or "").strip().upper()
    state_full = STATE_NAMES.get(state_abbr, state_abbr)
    city = (row.get("city") or "").strip()
    svc = services_lookup(row.get("services"))
    types = derive_types(svc); insurance = derive_insurance(svc)
    phone = (row.get("phone") or "").strip() or "Call for information"
    website = (row.get("website") or "").strip()
    lat = row.get("latitude"); lng = row.get("longitude")
    types_str = ", ".join(types) if types else "addiction treatment services"
    ins_str = ", ".join(i for i in insurance if i != "Contact for details") or "various payment options"
    description = f"SAMHSA-sourced treatment facility in {city}, {state_abbr}. Offers {types_str}. Accepts {ins_str}."
    return {
        "name": name, "city": city, "state": state_full, "stateAbbr": state_abbr,
        "phone": phone, "website": website,
        "latitude": str(lat) if lat is not None else "",
        "longitude": str(lng) if lng is not None else "",
        "types": types, "insurance": insurance, "description": description,
        "featured": False, "samhsa_verified": True, "curated": False,
        "refreshed_at": REFRESHED_AT,
    }


# ----- Identity keys (lat/lng primary, name+state+city fallback) ------------

def name_key(name, state_abbr, city):
    """Case-insensitive, punctuation-stripped, whitespace-collapsed key (fallback)."""
    n = (name or "").lower()
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return ("NAME", n, (state_abbr or "").upper().strip(), (city or "").lower().strip())


def coord_key(lat, lng):
    """Rounded (lat, lng) tuple. Returns None if either coord missing/invalid."""
    try:
        if lat in (None, "", "0", 0) or lng in (None, "", "0", 0):
            return None
        f_lat = round(float(lat), COORD_PRECISION)
        f_lng = round(float(lng), COORD_PRECISION)
        return ("COORD", f_lat, f_lng)
    except (ValueError, TypeError):
        return None


def identity_keys(record):
    """Return list of identity keys for a record (primary + fallback). Order matters: primary first."""
    keys = []
    ck = coord_key(record.get("latitude"), record.get("longitude"))
    if ck:
        keys.append(ck)
    keys.append(name_key(record.get("name"), record.get("stateAbbr"), record.get("city")))
    return keys


def build_keyset(records):
    """Return set of all identity keys across a record list (union of primary + fallback)."""
    s = set()
    for r in records:
        for k in identity_keys(r):
            s.add(k)
    return s


def record_matches_keyset(record, keyset):
    """True if any of the record's identity keys is in the keyset."""
    return any(k in keyset for k in identity_keys(record))


# ----- Dedup / diff -----------------------------------------------------------

def dedup_curated_samhsa(curated, samhsa):
    """Drop SAMHSA records that match curated by lat/lng OR name_norm+state+city."""
    curated_keyset = build_keyset(curated)
    kept, dropped_examples = [], []
    for r in samhsa:
        if record_matches_keyset(r, curated_keyset):
            if len(dropped_examples) < 5:
                dropped_examples.append(f"{r.get('name')} ({r.get('city')}, {r.get('stateAbbr')})")
            continue
        kept.append(r)
    dropped_n = len(samhsa) - len(kept)
    print(f"DEDUP: dropped {dropped_n} SAMHSA records that matched curated (lat/lng primary, name+state+city fallback)", flush=True)
    if dropped_examples:
        more = "..." if dropped_n > 5 else ""
        print(f"  Examples: {'; '.join(dropped_examples)}{more}", flush=True)
    return kept


def identify_enrichment_targets(deduped_samhsa, previous_facilities):
    """Net-new = no match in previous by lat/lng OR name+state+city. Weak-insurance = matched + has placeholder insurance."""
    prev_keyset = build_keyset(previous_facilities)
    net_new, weak_insurance = [], []
    for r in deduped_samhsa:
        if not record_matches_keyset(r, prev_keyset):
            net_new.append(r)
        elif r.get("insurance") == ["Contact for details"]:
            weak_insurance.append(r)
    print(f"TARGETS: {len(net_new)} net-new + {len(weak_insurance)} weak-insurance backfill = {len(net_new) + len(weak_insurance)} total", flush=True)
    return net_new, weak_insurance


# ----- Enrichment -------------------------------------------------------------

def serper_search(query, num=3):
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        raise RuntimeError("SERPER_API_KEY not set")
    body = json.dumps({"q": query, "num": num}).encode()
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=body,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
    )
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                d = json.load(resp)
            organic = d.get("organic", []) or []
            simplified = [
                {"title": r.get("title", ""), "link": r.get("link", ""), "snippet": r.get("snippet", "")}
                for r in organic[:num]
            ]
            return simplified, 1
        except Exception as e:
            last_err = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"Serper failed: {last_err}")


def haiku_enrich(facility, search_results):
    api_key = os.environ.get("ANTHROPIC_API_KEY_LOCAL") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY_LOCAL not set")
    types_str = ", ".join(facility.get("types") or []) or "(none from SAMHSA)"
    snippet_blocks = []
    for i, r in enumerate(search_results[:3], 1):
        snippet_blocks.append(f"[{i}] {r['title']}\n{r['link']}\n{r['snippet']}")
    snippets = "\n\n".join(snippet_blocks) if snippet_blocks else "(no relevant search results)"
    user_msg = (
        f"Facility:\n- Name: {facility.get('name')}\n"
        f"- Location: {facility.get('city')}, {facility.get('stateAbbr')}\n"
        f"- SAMHSA service types: {types_str}\n\n"
        f"Web search results (top {len(search_results[:3])}):\n{snippets}\n\n"
        "Produce JSON:\n"
        '{"description": "<2-3 sentence description grounded in snippets only; '
        'if snippets sparse, use minimal SAMHSA-fields-only template>",\n'
        f' "insurance": [<subset of: {", ".join(INSURANCE_VOCAB)}; or [] if unclear>],\n'
        ' "confidence": "high|medium|low"}'
    )
    payload = {
        "model": ENRICH_MODEL,
        "max_tokens": 400,
        "system": [{"type": "text", "text": ENRICH_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user_msg}],
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                d = json.load(resp)
            text = (d.get("content") or [{}])[0].get("text", "").strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
            parsed = json.loads(text)
            return parsed, d.get("usage", {})
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
            last_err = f"HTTP {e.code}: {err_body}"
            time.sleep(2 ** attempt)
        except Exception as e:
            last_err = str(e)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Haiku call failed: {last_err}")


def estimate_cost(usage_total):
    return (
        usage_total.get("anthropic_input_tokens", 0) / 1_000_000 * HAIKU_INPUT_PRICE_PER_M
        + usage_total.get("anthropic_output_tokens", 0) / 1_000_000 * HAIKU_OUTPUT_PRICE_PER_M
        + usage_total.get("anthropic_cache_creation", 0) / 1_000_000 * HAIKU_CACHE_WRITE_PRICE_PER_M
        + usage_total.get("anthropic_cache_read", 0) / 1_000_000 * HAIKU_CACHE_READ_PRICE_PER_M
        + usage_total.get("serper_credits", 0) * SERPER_PRICE_PER_CREDIT
    )


def enrich_facility(facility, usage_total, rewrite_description=True):
    name = facility.get("name", "")
    city = facility.get("city", "")
    state = facility.get("stateAbbr", "")
    query = f"{name} {city} {state} addiction treatment center insurance"
    try:
        results, credits = serper_search(query, num=3)
        usage_total["serper_credits"] += credits
    except Exception as e:
        print(f"  ! Serper failed for {name}: {e}", flush=True)
        return False
    try:
        parsed, usage = haiku_enrich(facility, results)
    except Exception as e:
        print(f"  ! Haiku failed for {name}: {e}", flush=True)
        return False
    usage_total["anthropic_input_tokens"] += usage.get("input_tokens", 0)
    usage_total["anthropic_output_tokens"] += usage.get("output_tokens", 0)
    usage_total["anthropic_cache_creation"] += usage.get("cache_creation_input_tokens", 0)
    usage_total["anthropic_cache_read"] += usage.get("cache_read_input_tokens", 0)
    new_desc = (parsed.get("description") or "").strip()
    new_ins = parsed.get("insurance") or []
    confidence = parsed.get("confidence", "low")
    if rewrite_description and new_desc:
        facility["description"] = new_desc
    if new_ins:
        cleaned = [v for v in new_ins if v in INSURANCE_VOCAB]
        if cleaned:
            facility["insurance"] = cleaned
    facility["enriched_at"] = REFRESHED_AT
    facility["enrichment_confidence"] = confidence
    return True


def enrich_batch(targets, label, usage_total, rewrite_description=True, halt_at=BUDGET_HARD_CAP):
    success = fail = 0
    halted = False
    n = len(targets)
    print(f"\n=== Enriching {label}: {n} records ===", flush=True)
    for i, r in enumerate(targets):
        if enrich_facility(r, usage_total, rewrite_description=rewrite_description):
            success += 1
        else:
            fail += 1
        if (i + 1) % 25 == 0:
            cost = estimate_cost(usage_total)
            print(f"  {label} {i+1}/{n} | cost ${cost:.3f} | success {success} fail {fail}", flush=True)
            if cost > halt_at:
                print(f"  ! HALT: cost ${cost:.3f} exceeds ${halt_at:.2f} cap", flush=True)
                halted = True
                break
        if (i + 1) % 100 == 0:
            enriched_so_far = [t for t in targets[: i + 1] if t.get("enriched_at") == REFRESHED_AT]
            if enriched_so_far:
                sample = random.sample(enriched_so_far, min(5, len(enriched_so_far)))
                print(f"  --- Quality spot-check (5 of {len(enriched_so_far)} enriched in {label}) ---", flush=True)
                for s in sample:
                    print(f"    [{s.get('enrichment_confidence', '?')}] {s['name']} ({s['city']}, {s['stateAbbr']})", flush=True)
                    print(f"      {s['description'][:240]}", flush=True)
                    print(f"      insurance: {s['insurance']}", flush=True)
                print(f"  --- end spot-check ---", flush=True)
    print(f"=== {label} complete: {success}/{n} succeeded, {fail} failed, halted={halted} ===", flush=True)
    return success, fail, halted


def main():
    with open(FACILITIES_PATH, encoding="utf-8") as f:
        previous = json.load(f)
    curated = [r for r in previous if r.get("curated")]
    print(f"Loaded {len(previous)} previous records ({len(curated)} curated)", flush=True)

    all_rows = []
    page = 1
    total_pages = None
    while True:
        print(f"Fetching page {page}...", flush=True)
        data = fetch_page(page)
        rows = data.get("rows", [])
        all_rows.extend(rows)
        record_count = data.get("recordCount")
        if total_pages is None and record_count is not None:
            total_pages = (record_count + PAGE_SIZE - 1) // PAGE_SIZE
            print(f"  recordCount={record_count}, total_pages={total_pages}", flush=True)
        if not rows or len(rows) < PAGE_SIZE:
            break
        if total_pages and page >= total_pages:
            break
        page += 1
    print(f"Fetched {len(all_rows)} raw SAMHSA rows", flush=True)

    sa_rows = [r for r in all_rows if r.get("typeFacility") == "SA"]
    print(f"Filtered to {len(sa_rows)} SA rows", flush=True)
    samhsa = [normalize(r) for r in sa_rows]

    samhsa_deduped = dedup_curated_samhsa(curated, samhsa)
    for r in curated:
        r["refreshed_at"] = REFRESHED_AT

    net_new, weak_insurance = identify_enrichment_targets(samhsa_deduped, previous)

    usage_total = {
        "anthropic_input_tokens": 0,
        "anthropic_output_tokens": 0,
        "anthropic_cache_creation": 0,
        "anthropic_cache_read": 0,
        "serper_credits": 0,
    }
    halted_overall = False
    if net_new:
        _, _, halted = enrich_batch(net_new, "net-new", usage_total, rewrite_description=True)
        halted_overall = halted_overall or halted
    if weak_insurance and not halted_overall:
        _, _, halted = enrich_batch(weak_insurance, "weak-insurance", usage_total, rewrite_description=False)
        halted_overall = halted_overall or halted

    final_cost = estimate_cost(usage_total)
    print(f"\n=== Enrichment cost summary ===", flush=True)
    print(f"  Anthropic input tokens:   {usage_total['anthropic_input_tokens']:,}", flush=True)
    print(f"  Anthropic output tokens:  {usage_total['anthropic_output_tokens']:,}", flush=True)
    print(f"  Anthropic cache writes:   {usage_total['anthropic_cache_creation']:,}", flush=True)
    print(f"  Anthropic cache reads:    {usage_total['anthropic_cache_read']:,}", flush=True)
    print(f"  Serper credits:           {usage_total['serper_credits']:,}", flush=True)
    print(f"  TOTAL COST:               ${final_cost:.4f}", flush=True)
    print(f"  Halted at cap:            {halted_overall}", flush=True)

    merged = curated + samhsa_deduped
    print(f"\nFinal merged: {len(merged)} ({len(curated)} curated + {len(samhsa_deduped)} SAMHSA)", flush=True)

    with open(FACILITIES_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {FACILITIES_PATH}", flush=True)

    stats_path = os.path.join(REPO_ROOT, ".enrichment_stats.json")
    with open(stats_path, "w") as f:
        json.dump({
            "refreshed_at": REFRESHED_AT,
            "usage": usage_total,
            "cost_usd": round(final_cost, 4),
            "halted": halted_overall,
            "net_new_count": len(net_new),
            "weak_insurance_count": len(weak_insurance),
        }, f, indent=2)


if __name__ == "__main__":
    main()
