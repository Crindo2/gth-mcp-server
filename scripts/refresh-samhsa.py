#!/usr/bin/env python3
"""
SAMHSA monthly refresh for gth-mcp-server.

Fetches SA-only facility data from findtreatment.gov, normalizes to the
existing facilities.json schema, preserves curated records, and writes
the merged result.

Schema fields preserved on curated records (curated=true): unchanged.
Schema fields written for SAMHSA records:
  name, city, state, stateAbbr, types[], insurance[], phone, website,
  description, latitude, longitude, samhsa_verified, curated, featured,
  refreshed_at
"""
import json
import os
import sys
import urllib.request
import urllib.parse
import time
from datetime import date

REFRESHED_AT = date.today().isoformat()
API_BASE = "https://findtreatment.gov/locator/exportsAsJson/v2"
PAGE_SIZE = 1000

# Resolve facilities.json relative to repo root (script lives in scripts/).
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
    """Return {f2_code: f3_value} dict from services list."""
    out = {}
    for s in services or []:
        code = s.get("f2")
        val = s.get("f3") or ""
        if code:
            out[code] = val
    return out


def derive_types(svc):
    """Derive types[] from SAMHSA services."""
    types = []
    setting = (svc.get("SET") or "").lower()
    # Order of insertion mirrors typical existing record order
    if "hospital inpatient" in setting or "residential" in setting:
        types.append("Inpatient Rehab")
    if "detox" in setting:
        types.append("Detox")
    if "intensive outpatient" in setting or "partial hospitalization" in setting or "day treatment" in setting:
        types.append("IOP (Intensive Outpatient)")
    if "outpatient" in setting and "Outpatient" not in types:
        types.append("Outpatient")
    # MAT — opioid medications used in treatment OR opioid treatment type
    if svc.get("OM") or svc.get("OT"):
        types.append("MAT (Medication-Assisted Treatment)")
    # Counseling — look for SUD counseling in treatment approaches or education/counseling services
    tap = (svc.get("TAP") or "").lower()
    ecs = (svc.get("ECS") or "").lower()
    if "counseling" in tap or "counseling" in ecs:
        types.append("Counseling")
    # Dedup preserving order
    seen = set()
    out = []
    for t in types:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def derive_insurance(svc):
    """Derive insurance[] from PAY service code."""
    pay = (svc.get("PAY") or "").lower()
    out = []
    if "private health insurance" in pay or "commercial" in pay:
        out.append("Most Major Insurance")
    if "medicare" in pay:
        out.append("Medicare")
    if "medicaid" in pay:
        out.append("Medicaid")
    if "tricare" in pay or "military insurance" in pay:
        out.append("Tricare")
    if "sliding fee" in pay or "sliding scale" in pay:
        out.append("Sliding Scale")
    if not out:
        out.append("Contact for details")
    return out


def normalize(row):
    name1 = (row.get("name1") or "").strip()
    name2 = (row.get("name2") or "").strip()
    name = name1 if not name2 else f"{name1} - {name2}" if name2 and name1 else (name1 or name2)
    name = name or "Unknown Facility"

    state_abbr = (row.get("state") or "").strip().upper()
    state_full = STATE_NAMES.get(state_abbr, state_abbr)
    city = (row.get("city") or "").strip()

    svc = services_lookup(row.get("services"))
    types = derive_types(svc)
    insurance = derive_insurance(svc)

    phone = (row.get("phone") or "").strip() or "Call for information"
    website = (row.get("website") or "").strip()
    lat = row.get("latitude")
    lng = row.get("longitude")

    types_str = ", ".join(types) if types else "addiction treatment services"
    ins_str = ", ".join(i for i in insurance if i != "Contact for details") or "various payment options"
    description = f"SAMHSA-verified treatment facility in {city}, {state_abbr}. Offers {types_str}. Accepts {ins_str}."

    return {
        "name": name,
        "city": city,
        "state": state_full,
        "stateAbbr": state_abbr,
        "phone": phone,
        "website": website,
        "latitude": str(lat) if lat is not None else "",
        "longitude": str(lng) if lng is not None else "",
        "types": types,
        "insurance": insurance,
        "description": description,
        "featured": False,
        "samhsa_verified": True,
        "curated": False,
        "refreshed_at": REFRESHED_AT,
    }


def main():
    # 1. Load existing facilities.json to preserve curated records
    with open(FACILITIES_PATH, encoding="utf-8") as f:
        existing = json.load(f)
    curated = [r for r in existing if r.get("curated")]
    print(f"Preserving {len(curated)} curated records", flush=True)

    # 2. Fetch all SAMHSA pages
    page = 1
    all_rows = []
    total_pages = None
    while True:
        print(f"Fetching page {page}...", flush=True)
        data = fetch_page(page)
        rows = data.get("rows", [])
        all_rows.extend(rows)
        record_count = data.get("recordCount")
        if total_pages is None and record_count is not None:
            total_pages = (record_count + PAGE_SIZE - 1) // PAGE_SIZE
            print(f"  recordCount={record_count}, computed total_pages={total_pages}", flush=True)
        if not rows or len(rows) < PAGE_SIZE:
            break
        if total_pages and page >= total_pages:
            break
        page += 1

    print(f"Fetched {len(all_rows)} raw SAMHSA rows", flush=True)

    # 3. Normalize SA-only (filter typeFacility=='SA' as belt-and-suspenders)
    sa_rows = [r for r in all_rows if r.get("typeFacility") == "SA"]
    print(f"Filtered to {len(sa_rows)} SA-typeFacility rows", flush=True)
    samhsa_records = [normalize(r) for r in sa_rows]
    print(f"Normalized {len(samhsa_records)} SAMHSA records", flush=True)

    # 4. Add refreshed_at to curated records too
    for r in curated:
        r["refreshed_at"] = REFRESHED_AT

    # 5. Combine: curated first (preserve "featured" ordering), then SAMHSA
    merged = curated + samhsa_records
    print(f"Total merged: {len(merged)} ({len(curated)} curated + {len(samhsa_records)} SAMHSA)", flush=True)

    # 6. Write
    with open(FACILITIES_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, separators=(",", ":"))

    print("Wrote facilities.json", flush=True)


if __name__ == "__main__":
    main()
