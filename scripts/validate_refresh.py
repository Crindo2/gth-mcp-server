#!/usr/bin/env python3
"""C716 s.3 fail-closed gates; no network and no model.
Usage: validate_refresh.py <prior committed JSON> <candidate JSON> [summary JSON]
Only a successful run writes the commit summary.
"""
import json
import sys
from pathlib import Path
from refresh_identity import IdentityIndex, match_retained, nonempty, protected_fields

MIN_ABS = 10000


def validate(base, new):
    IdentityIndex(base)
    IdentityIndex(new)
    matches = match_retained(base, new)
    states = {r["stateAbbr"] for r in base}
    if any(r["stateAbbr"] not in states for r in new):
        raise ValueError("IDENTITY: stateAbbr not present in prior committed file")
    retained = set(matches.values())
    reverse = {j: i for i, j in matches.items()}
    for j, record in enumerate(base):
        if record.get("curated"):
            if j not in retained:
                raise ValueError("IDENTITY: prior curated identity missing")
            if {k: v for k, v in new[reverse[j]].items() if k != "refreshed_at"} != {
                    k: v for k, v in record.items() if k != "refreshed_at"}:
                raise ValueError("IDENTITY: prior curated record changed")
    if sum(bool(r.get("curated")) for r in base) != sum(bool(r.get("curated")) for r in new):
        raise ValueError("IDENTITY: curated count changed")
    if len(new) < MIN_ABS or len(new) * 100 < len(base) * 98:
        raise ValueError("COMPLETION: need >=10000 AND >=98% of prior committed count")
    for i, j in matches.items():
        for field, value in protected_fields(base[j]).items():
            if field not in new[i] or new[i][field] != value:
                raise ValueError(f"ENRICHMENT: retained record {j} changed or lost {field}")
    for j, record in enumerate(base):
        if nonempty(record.get("enriched_at")) and j not in retained:
            raise ValueError(f"ENRICHMENT: enriched prior identity {j} missing")
    for field, percent in (("enriched_at", 98), ("description", 99), ("website", 98)):
        b = sum(nonempty(r.get(field)) for r in base)
        n = sum(nonempty(r.get(field)) for r in new)
        if n * 100 < b * percent:
            raise ValueError("ENRICHMENT: aggregate non-regression for " + field)
    return {"facilities": len(new), "previous": len(base),
            "enriched": sum(nonempty(r.get("enriched_at")) for r in new),
            "curated": sum(bool(r.get("curated")) for r in new)}


def main():
    summary = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    if summary:
        summary.unlink(missing_ok=True)
    try:
        base = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        new = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        result = validate(base, new)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print("GATE FAILED:", exc)
        return 1
    if summary:
        summary.write_text(json.dumps(result), encoding="utf-8")
    print("GATES PASSED: identity, completion, enrichment", json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
