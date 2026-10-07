#!/usr/bin/env python3
"""Deterministic gates for the SAMHSA monthly refresh (C716 s.3). No model, no network.

Usage: python3 scripts/validate_refresh.py <base facilities.json> <new facilities.json> [summary.json]

Gates (any failure exits 1 and nothing is committed or deployed):
  IDENTITY    new file is a list of objects; >= 99.9% have non-empty name, city, state, stateAbbr; every stateAbbr is one the previous file already used;
              the curated records of the previous file are all still present (same curated count).
  COMPLETION  record count >= 10,000 AND >= 98% of the previous count.
  ENRICHMENT  existing enrichment is preserved: records with enriched_at, non-empty description and non-empty website must not fall below 98% / 99% / 98% of the previous counts.
Writes a one-line summary (counts) for the commit message to the optional third argument.
"""
import json
import sys

MIN_ABS = 10000
MIN_RATIO = 0.98


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def nonempty(v):
    return v not in (None, "", [], {})


def count(records, field):
    return sum(1 for r in records if nonempty(r.get(field)))


def main():
    base, new = load(sys.argv[1]), load(sys.argv[2])
    fails = []
    # IDENTITY
    if not isinstance(new, list) or not all(isinstance(r, dict) for r in new):
        print("GATE IDENTITY FAILED: facilities file is not a list of objects")
        sys.exit(1)
    req = ("name", "city", "state", "stateAbbr")
    ok = sum(1 for r in new if all(nonempty(r.get(k)) for k in req))
    if new and ok / len(new) < 0.999:
        fails.append(f"IDENTITY: only {ok}/{len(new)} records have name, city, state and stateAbbr")
    base_states = {r.get("stateAbbr") for r in base}
    odd = sorted({r.get("stateAbbr") for r in new} - base_states)
    if odd:
        fails.append(f"IDENTITY: stateAbbr values not seen in the previous file: {odd[:8]}")
    bc, nc = sum(1 for r in base if r.get("curated")), sum(1 for r in new if r.get("curated"))
    if nc != bc:
        fails.append(f"IDENTITY: curated records changed {bc} -> {nc}")
    # COMPLETION
    if len(new) < MIN_ABS:
        fails.append(f"COMPLETION: {len(new)} records < {MIN_ABS}")
    if len(new) < MIN_RATIO * len(base):
        fails.append(f"COMPLETION: {len(new)} records < {MIN_RATIO:.0%} of previous {len(base)}")
    # ENRICHMENT
    for field, ratio in (("enriched_at", 0.98), ("description", 0.99), ("website", 0.98)):
        b, n = count(base, field), count(new, field)
        if b and n < ratio * b:
            fails.append(f"ENRICHMENT: {field} populated on {n} records, below {ratio:.0%} of previous {b}")
    enriched = count(new, "enriched_at")
    line = {"facilities": len(new), "previous": len(base), "enriched": enriched, "curated": nc}
    print("GATES:", json.dumps(line))
    if len(sys.argv) > 3:
        with open(sys.argv[3], "w", encoding="utf-8") as f:
            json.dump(line, f)
    if fails:
        for m in fails:
            print("GATE FAILED -", m)
        sys.exit(1)
    print("GATES PASSED: identity, completion, enrichment")


if __name__ == "__main__":
    main()
