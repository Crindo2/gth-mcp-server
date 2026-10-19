"""Full merge and validator controls for the two co-located identity defects."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_monthly_refresh import record, refresh, validate, forbidden
from refresh_identity import IdentityIndex, ENRICHMENT_FIELDS, stable_key


class CoLocatedIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = [record(i) for i in range(10000)]

    def new_operator(self):
        new = copy.deepcopy(self.base[0])
        new["name"] = "Independent New Operator"
        for field in ENRICHMENT_FIELDS:
            new.pop(field, None)
        new.update(description="New operator source description",
                   website="https://new-operator.invalid",
                   insurance=["New operator payment option"])
        return new

    def test_coordinates_alone_do_not_resolve_identity(self):
        self.assertIsNone(IdentityIndex(self.base).match(self.new_operator()))

    def test_replacement_full_merge_refuses_unresolved_alias(self):
        incoming = copy.deepcopy(self.base)
        incoming[0] = self.new_operator()
        with self.assertRaisesRegex(ValueError, "IDENTITY.*coordinate-only alias"):
            refresh.merge_records(self.base, incoming)

    def test_replacement_validator_refuses_even_with_copied_enrichment(self):
        candidate = copy.deepcopy(self.base)
        candidate[0]["name"] = self.new_operator()["name"]
        with self.assertRaisesRegex(ValueError, "IDENTITY.*coordinate-only alias"):
            validate(self.base, candidate)

    def test_replacement_without_marker_is_replaced_not_refused(self):
        # C992 revised s.1: an unenriched, uncurated prior at the same coordinates has nothing to lose; it is replaced.
        base = copy.deepcopy(self.base)
        base[0].pop("enriched_at")
        incoming = copy.deepcopy(base)
        incoming[0] = self.new_operator()
        merged, _ = refresh.merge_records(base, incoming)
        self.assertIn(self.new_operator()["name"], [r["name"] for r in merged])
        self.assertNotIn(base[0]["name"], [r["name"] for r in merged])

    def test_enriched_replacement_at_same_coordinates_still_refuses(self):
        base = copy.deepcopy(self.base)                 # base[0] carries enriched_at
        incoming = copy.deepcopy(base)
        incoming[0] = self.new_operator()
        with self.assertRaisesRegex(ValueError, "IDENTITY.*coordinate-only alias"):
            refresh.merge_records(base, incoming)

    def test_full_main_alias_failure_leaves_previous_and_queue_untouched(self):
        incoming = copy.deepcopy(self.base)
        incoming[0] = self.new_operator()
        rows = [{"name1": r["name"], "city": r["city"], "state": r["stateAbbr"],
                 "latitude": r["latitude"], "longitude": r["longitude"],
                 "typeFacility": "SA"} for r in incoming]
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "facilities.json"
            file.write_text(json.dumps(self.base), encoding="utf-8")
            queue = Path(tmp) / "enrichment-queue.json"
            queue.write_text('{"previous_queue":true}', encoding="utf-8")
            before, before_queue = file.read_bytes(), queue.read_bytes()
            def fetch(page):
                return {"recordCount": len(rows),
                        "rows": rows[(page - 1) * 1000:page * 1000]}
            with patch.object(refresh, "REPO_ROOT", tmp), \
                 patch.object(refresh, "FACILITIES_PATH", str(file)), \
                 patch.object(refresh, "fetch_page", fetch), \
                 patch.object(refresh.urllib.request, "urlopen", forbidden), \
                 patch("sys.stdout", new_callable=io.StringIO):
                with self.assertRaisesRegex(ValueError, "IDENTITY"):
                    refresh.main()
            self.assertEqual(file.read_bytes(), before)
            self.assertEqual(queue.read_bytes(), before_queue)

    def check_neighbor(self, curated):
        base = copy.deepcopy(self.base)
        base[0]["curated"] = curated
        base[0]["verified_program_details"] = {"source": "prior-only"}
        incoming = copy.deepcopy(self.base) + [self.new_operator()]
        merged, queue = refresh.merge_records(base, incoming)
        self.assertEqual(len(merged), 10001)
        self.assertEqual(validate(base, merged)["facilities"], 10001)
        neighbor = next(r for r in merged if r["name"] == self.new_operator()["name"])
        self.assertNotEqual(stable_key(neighbor), stable_key(base[0]))
        for field in ("description", "website", "insurance"):
            self.assertEqual(neighbor[field], self.new_operator()[field])
        for field in ("enriched_at", "enrichment_confidence", "verified_program_details"):
            self.assertNotIn(field, neighbor)
        retained = next(r for r in merged if stable_key(r) == stable_key(base[0]))
        for field in ENRICHMENT_FIELDS | {"verified_program_details"}:
            self.assertEqual(retained[field], base[0][field])
        self.assertEqual(queue, [{"name": neighbor["name"], "city": neighbor["city"],
                                 "stateAbbr": neighbor["stateAbbr"], "reason": "net-new"}])

    def test_curated_colocated_new_operator_preserved_and_queued(self):
        self.check_neighbor(True)

    def test_noncurated_colocated_new_operator_preserved_and_queued(self):
        self.check_neighbor(False)

    def test_colocated_retained_and_same_name_branches_keep_own_enrichment(self):
        for same_name in (False, True):
            with self.subTest(same_name=same_name):
                base = copy.deepcopy(self.base)
                if same_name:
                    base[1]["name"] = base[0]["name"]
                else:
                    base[1]["latitude"] = base[0]["latitude"]
                    base[1]["longitude"] = base[0]["longitude"]
                base[0]["description"], base[1]["description"] = "Operator zero", "Operator one"
                merged, queue = refresh.merge_records(base, copy.deepcopy(base))
                self.assertEqual(validate(base, merged)["facilities"], 10000)
                self.assertEqual([r["description"] for r in merged[:2]],
                                 ["Operator zero", "Operator one"])
                self.assertEqual(queue, [])

    def test_unique_name_missing_coordinates_retains_enrichment(self):
        incoming = copy.deepcopy(self.base)
        incoming[0]["latitude"] = incoming[0]["longitude"] = ""
        incoming[0].pop("enrichment_confidence")
        merged, queue = refresh.merge_records(self.base, incoming)
        self.assertEqual(validate(self.base, merged)["facilities"], 10000)
        self.assertEqual(merged[0]["enrichment_confidence"], "high")
        self.assertEqual(queue, [])
