"""Shared, deterministic identity and preservation rules for the monthly rail."""
import math
import re
from copy import deepcopy

ENRICHMENT_FIELDS = frozenset((
    "description", "website", "insurance", "enriched_at", "enrichment_confidence",
))
SOURCE_FIELDS = frozenset((
    "name", "city", "state", "stateAbbr", "latitude", "longitude", "phone",
    "types", "featured", "samhsa_verified", "curated", "refreshed_at",
)) | ENRICHMENT_FIELDS


def nonempty(value):
    return value not in (None, "", [], {})


def name_key(record):
    parts = []
    for field in ("name", "stateAbbr", "city"):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("IDENTITY: missing or invalid " + field)
        value = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value.casefold())).strip()
        if not value or (field == "name" and value == "unknown facility"):
            raise ValueError("IDENTITY: unusable " + field)
        parts.append(value)
    if not isinstance(record.get("state"), str) or not record["state"].strip():
        raise ValueError("IDENTITY: missing or invalid state")
    return tuple(parts)


def coord_key(record):
    lat, lng = record.get("latitude"), record.get("longitude")
    if lat in (None, "", 0, "0") or lng in (None, "", 0, "0"):
        return None
    try:
        lat, lng = float(lat), float(lng)
    except (ValueError, TypeError) as exc:
        raise ValueError("IDENTITY: invalid coordinates") from exc
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("IDENTITY: invalid coordinates")
    return round(lat, 5), round(lng, 5)


def stable_key(record):
    # Co-located facilities and separate branches with the same name remain distinct.
    return name_key(record), coord_key(record)


class IdentityIndex:
    def __init__(self, records):
        if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
            raise ValueError("IDENTITY: expected a list of objects")
        self.records = records
        self.names, self.coords, self.full = {}, {}, {}
        for i, record in enumerate(records):
            nk, ck = stable_key(record)
            if (nk, ck) in self.full:
                raise ValueError(f"IDENTITY: duplicate stable identity at records {self.full[nk, ck]} and {i}")
            self.full[nk, ck] = i
            self.names.setdefault(nk, set()).add(i)
            if ck is not None:
                self.coords.setdefault(ck, set()).add(i)

    def match(self, record):
        nk, ck = stable_key(record)
        by_name = self.names.get(nk, set())
        by_coord = self.coords.get(ck, set()) if ck is not None else set()
        if by_name and by_coord:
            choices = by_name & by_coord
            if not choices:
                raise ValueError("IDENTITY: name and coordinates identify different facilities")
        else:
            choices = by_name or by_coord
        if len(choices) > 1:
            raise ValueError("IDENTITY: ambiguous match")
        return next(iter(choices)) if choices else None


def match_retained(previous, candidate):
    old, new = IdentityIndex(previous), IdentityIndex(candidate)
    matched, used = {}, set()
    for i, record in enumerate(candidate):
        j = old.match(record)
        if j is not None:
            if j in used:
                raise ValueError("IDENTITY: multiple candidates match one prior facility")
            # Enforce reciprocal resolution, including missing-coordinate ambiguities.
            if new.match(previous[j]) != i:
                raise ValueError("IDENTITY: match is not reciprocal")
            matched[i] = j
            used.add(j)
    return matched


def protected_fields(record):
    # Unknown future fields are carried and checked, rather than silently discarded.
    return {k: deepcopy(v) for k, v in record.items()
            if k not in SOURCE_FIELDS or
            (k in ENRICHMENT_FIELDS and (nonempty(v) or nonempty(record.get("enriched_at"))))}


def deduplicate(records):
    """Drop identical incoming duplicates; refuse conflicting duplicates."""
    kept, seen = [], {}
    for record in records:
        key = stable_key(record)
        if key in seen:
            if record != seen[key]:
                raise ValueError("IDENTITY: conflicting duplicate source records")
            continue
        seen[key] = record
        kept.append(record)
    IdentityIndex(kept)
    return kept
