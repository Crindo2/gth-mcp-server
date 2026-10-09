#!/usr/bin/env python3
"""C716 s.3: fetch SAMHSA, deduplicate, carry enrichment, and queue new work.

This script has no model/search implementation or opt-in enrichment path.
Candidate data must pass validate_refresh.py before any commit or deployment.
"""
import json
import os
import urllib.request
import urllib.parse
import time
from copy import deepcopy
from datetime import date
from refresh_identity import (IdentityIndex, deduplicate, match_retained,
                              protected_fields)

REFRESHED_AT = date.today().isoformat()
API_BASE = "https://findtreatment.gov/locator/exportsAsJson/v2"
PAGE_SIZE = 1000
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACILITIES_PATH = os.path.join(REPO_ROOT, "facilities.json")

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



def merge_records(previous, incoming):
    IdentityIndex(previous)  # Never choose enrichment from an ambiguous prior identity.
    curated = [deepcopy(r) for r in previous if r.get("curated")]
    curated_index = IdentityIndex(curated)
    incoming = deduplicate(incoming)
    fresh = [deepcopy(r) for r in incoming if curated_index.match(r) is None]
    retained = match_retained(previous, curated + fresh)
    merged = curated + fresh
    for i, j in retained.items():
        merged[i].update(protected_fields(previous[j]))
    for record in curated:
        record["refreshed_at"] = REFRESHED_AT
    queue = []
    for i, record in enumerate(merged):
        if record.get("curated"):
            continue
        reason = "net-new" if i not in retained else (
            "weak-insurance" if record.get("insurance") == ["Contact for details"] else None)
        if reason:
            queue.append({"name": record["name"], "city": record["city"],
                          "stateAbbr": record["stateAbbr"], "reason": reason})
    return merged, queue


def main():
    with open(FACILITIES_PATH, encoding="utf-8") as f:
        previous = json.load(f)
    IdentityIndex(previous)
    all_rows, page, expected = [], 1, None
    while True:
        data = fetch_page(page)
        rows, count = data.get("rows"), data.get("recordCount")
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise ValueError("COMPLETION: malformed SAMHSA page")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValueError("COMPLETION: missing or invalid recordCount")
        if expected is None:
            expected = count
        if count != expected:
            raise ValueError("COMPLETION: source recordCount changed while fetching")
        all_rows.extend(rows)
        if len(all_rows) > expected:
            raise ValueError("COMPLETION: source exceeds its declared count")
        if len(all_rows) == expected:
            break
        if len(rows) != PAGE_SIZE:
            raise ValueError("COMPLETION: truncated source page")
        page += 1
    samhsa = [normalize(r) for r in all_rows if r.get("typeFacility") == "SA"]
    merged, queue = merge_records(previous, samhsa)
    print(f"FETCH: {len(all_rows)} rows; DEDUP/MERGE: {len(merged)} facilities; QUEUE: {len(queue)}")
    # Do not write either file until fetch, identity resolution and preservation complete.
    with open(os.path.join(REPO_ROOT, "enrichment-queue.json"), "w", encoding="utf-8") as f:
        json.dump({"refreshed_at": REFRESHED_AT, "count": len(queue), "queue": queue},
                  f, ensure_ascii=False, indent=1)
    with open(FACILITIES_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, separators=(",", ":"))
    print("Candidate written; run all three gates before commit or deploy")


if __name__ == "__main__":
    main()
