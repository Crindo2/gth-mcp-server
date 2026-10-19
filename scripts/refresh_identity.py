"""Shared, deterministic identity and preservation rules for the monthly rail."""
import math
import re
from copy import deepcopy

ENRICHMENT_FIELDS = frozenset((
    "description", "website", "insurance", "enriched_at", "enrichment_confidence",
))
SOURCE_FIELDS = frozenset((
    "name", "city", "state", "stateAbbr", "latitude", "longitude", "phone",
    "street", "zip", "phone_verify_directly",
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


def _text(value):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(value or "").casefold())).strip()


def zip5(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[:5] if len(digits) >= 5 else ""


def address_key(record):
    street, zipcode = _text(record.get("street")), zip5(record.get("zip"))
    return (street, zipcode) if street and zipcode else None


def phone_digits(record):
    digits = re.sub(r"\D", "", str(record.get("phone") or ""))
    return digits[:10] if len(digits) >= 10 else ""


def place_key(record):
    """Where the facility is: street+ZIP when known; else coordinates; else the phone (never merges different places)."""
    address = address_key(record)
    if address:
        return ("addr",) + address
    coords = coord_key(record)
    if coords is not None:
        return ("geo",) + coords
    phone = phone_digits(record)
    return ("tel", phone) if phone else None


def stable_key(record):
    # Facility identity = name + street + city + ZIP (C992 revised s.1). Branches with the same name stay separate.
    return name_key(record), place_key(record)


class IdentityIndex:
    def __init__(self, records):
        if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
            raise ValueError("IDENTITY: expected a list of objects")
        self.records = records
        self.names, self.places, self.full, self.pks = {}, {}, {}, []
        for i, record in enumerate(records):
            nk, pk = stable_key(record)
            if (nk, pk) in self.full:
                raise ValueError(f"IDENTITY: duplicate stable identity at records {self.full[nk, pk]} and {i}")
            self.full[nk, pk] = i
            self.pks.append(pk)
            self.names.setdefault(nk, set()).add(i)
            if pk is not None:
                self.places.setdefault(pk, set()).add(i)

    def match(self, record):
        nk, pk = stable_key(record)
        names = self.names.get(nk, set())
        if not names:
            return None
        if pk is not None and pk[0] == "addr":
            same = {i for i in names if self.pks[i] == pk}
            # A prior record with no street yet may be this facility; one with a different street is another branch.
            choices = same or {i for i in names if not (self.pks[i] and self.pks[i][0] == "addr")}
        else:
            choices = set(names)
            if pk is not None:
                choices = {i for i in choices if self.pks[i] == pk} or choices
        if len(choices) > 1:
            phone = phone_digits(record)
            narrowed = {i for i in choices if phone and phone_digits(self.records[i]) == phone}
            if len(narrowed) == 1:
                choices = narrowed
        if len(choices) > 1:
            raise ValueError("IDENTITY: ambiguous match")
        return next(iter(choices)) if choices else None


def _safe_match(index, record):
    """An ambiguous identity is treated as no match (the record is carried as new), never as a failed run."""
    try:
        return index.match(record)
    except ValueError as exc:
        if "ambiguous" in str(exc):
            return None
        raise


def match_retained(previous, candidate):
    old, new = IdentityIndex(previous), IdentityIndex(candidate)
    matched, used = {}, set()
    same_name = {}
    for record in candidate:
        same_name[name_key(record)] = same_name.get(name_key(record), 0) + 1
    for i, record in enumerate(candidate):
        j = _safe_match(old, record)
        if j is not None and old.pks[j] is not None and old.pks[j][0] != "addr"                 and address_key(record) and same_name[name_key(record)] > 1:
            # A prior record with no street cannot be assigned to one of several same-name branches: its enrichment
            # (website, description) must never land on the wrong branch. The branch is carried as new.
            j = None
        if j is not None:
            if j in used:
                continue
            # Enforce reciprocal resolution. A match that is not reciprocal (a streetless prior record that could
            # be one of several same-name branches) is not trusted: the source record is carried as new, the run
            # does not fail, and the enrichment gate still refuses any real loss of enriched data (C992 revised s.1).
            if _safe_match(new, previous[j]) != i:
                continue
            matched[i] = j
            used.add(j)
    for i, record in enumerate(candidate):
        if i not in matched:
            ck = coord_key(record)
            at_place = old.places.get(("geo",) + ck, set()) - used if ck is not None else set()
            # A rename at the same coordinates can only cost enrichment or curation work, so only those priors force
            # a human data repair; an unenriched, uncurated prior is simply replaced by the new SAMHSA record (C992 revised s.1).
            if any(nonempty(previous[x].get("enriched_at")) or previous[x].get("curated") for x in at_place):
                # Co-located named operators may coexist. A missing prior operator
                # cannot be renamed using its coordinates alone; source evidence
                # for such an alias belongs in a separate data repair.
                raise ValueError("IDENTITY: unresolved coordinate-only alias")
    return matched


def protected_fields(record):
    # Unknown future fields are carried and checked, rather than silently discarded.
    return {k: deepcopy(v) for k, v in record.items()
            if k not in SOURCE_FIELDS or
            (k in ENRICHMENT_FIELDS and (nonempty(v) or nonempty(record.get("enriched_at"))))}


def deduplicate(records):
    """One record per facility. Identical duplicates collapse. Where the feed conflicts for one facility (same name and
    address), keep the first row in SAMHSA's order (the feed carries no update date) and mark the phone
    "Verify directly". Never two phones, never merged descriptions, never a failed run (C992 revised s.1)."""
    kept, seen = [], {}
    for record in records:
        key = stable_key(record)
        if key in seen:
            if record != seen[key]:
                seen[key]["phone_verify_directly"] = True
            continue
        seen[key] = record
        kept.append(record)
    IdentityIndex(kept)
    return kept
