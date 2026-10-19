"""Offline controls for every gate and VERIFY_FAIL defect; stdlib only.

Run from the repository: python -B -m unittest discover -s scripts/tests -v
All generated facilities and receipts live in TemporaryDirectory; no live calls.
"""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import pages_refresh as pages
from refresh_identity import IdentityIndex, deduplicate, stable_key
from validate_refresh import validate

spec = importlib.util.spec_from_file_location("refresh", SCRIPTS / "refresh-samhsa.py")
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


def record(i):
    return {"name": f"Fixture Facility {i:05d}", "city": "Fixture City", "state": "Illinois",
            "stateAbbr": "IL", "latitude": str(40 + i / 100000),
            "longitude": str(-89 - i / 100000), "curated": False, "featured": False,
            "description": "Preserved description", "website": "https://fixture.invalid",
            "insurance": ["Medicaid"], "enriched_at": "2026-09-01",
            "enrichment_confidence": "high", "types": ["Outpatient"],
            "phone": "Call for information", "samhsa_verified": True}


def forbidden(*args, **kwargs):
    raise AssertionError("Live network forbidden in offline controls")


def setUpModule():
    global network_guard
    network_guard = patch.object(pages.urllib.request, "urlopen", forbidden)
    network_guard.start()


def tearDownModule():
    network_guard.stop()


class Gates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = [record(i) for i in range(10000)]

    def test_positive_unchanged(self):
        self.assertEqual(validate(self.base, self.base)["facilities"], 10000)

    def test_completion_absolute_negative(self):
        with self.assertRaisesRegex(ValueError, "COMPLETION"):
            validate(self.base, self.base[:-1])

    def test_completion_ratio_negative_and_exact_boundary(self):
        base = [record(i) for i in range(12000)]
        for r in base[11760:]:
            for f in ("description", "website", "insurance", "enriched_at", "enrichment_confidence"):
                r.pop(f)
        with self.assertRaisesRegex(ValueError, "COMPLETION"):
            validate(base, base[:11759])
        self.assertEqual(validate(base, base[:11760])["facilities"], 11760)

    def test_duplicate_identity_rejected_even_at_10000(self):
        new = copy.deepcopy(self.base)
        new[-1] = copy.deepcopy(new[0])
        with self.assertRaisesRegex(ValueError, "IDENTITY.*duplicate"):
            validate(self.base, new)

    def test_ambiguous_aliases_refused(self):
        new = copy.deepcopy(self.base)
        new[0]["name"] = new[1]["name"]
        with self.assertRaisesRegex(ValueError, "IDENTITY"):
            validate(self.base, new)

    def test_many_to_one_refused(self):
        new = copy.deepcopy(self.base)
        new[-1] = copy.deepcopy(new[0])
        new[-1]["name"] = "Renamed duplicate"
        with self.assertRaisesRegex(ValueError, "IDENTITY"):
            validate(self.base, new)

    def test_duplicate_prior_refused(self):
        base = copy.deepcopy(self.base)
        base[-1] = copy.deepcopy(base[0])
        with self.assertRaisesRegex(ValueError, "IDENTITY.*duplicate"):
            validate(base, self.base)

    def test_missing_one_required_field_refused(self):
        for field in ("name", "city", "state", "stateAbbr"):
            with self.subTest(field=field):
                new = copy.deepcopy(self.base)
                new[0].pop(field)
                with self.assertRaisesRegex(ValueError, "IDENTITY"):
                    validate(self.base, new)

    def test_invalid_state_refused(self):
        new = copy.deepcopy(self.base)
        new[0]["stateAbbr"] = "ZZ"
        with self.assertRaisesRegex(ValueError, "IDENTITY"):
            validate(self.base, new)

    def test_invalid_coordinates_refused(self):
        for value in ("nan", "inf", "91", "bad"):
            with self.subTest(value=value):
                new = copy.deepcopy(self.base)
                new[0]["latitude"] = value
                with self.assertRaisesRegex(ValueError, "IDENTITY"):
                    validate(self.base, new)

    def test_colocated_and_separate_branches_are_distinct(self):
        colocated = [record(0), record(1)]
        colocated[1]["latitude"] = colocated[0]["latitude"]
        colocated[1]["longitude"] = colocated[0]["longitude"]
        self.assertNotEqual(stable_key(colocated[0]), stable_key(colocated[1]))
        self.assertIsNotNone(IdentityIndex(colocated))
        branches = [record(0), record(1)]
        branches[1]["name"] = branches[0]["name"]
        self.assertIsNotNone(IdentityIndex(branches))
        missing = copy.deepcopy(branches[0])
        missing["latitude"] = missing["longitude"] = ""
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            IdentityIndex(branches).match(missing)

    def test_curated_swap_at_same_count_refused(self):
        base = copy.deepcopy(self.base)
        base[0]["curated"] = True
        new = copy.deepcopy(base)
        new[0]["curated"] = False
        new[1]["curated"] = True
        with self.assertRaisesRegex(ValueError, "IDENTITY.*curated"):
            validate(base, new)

    def test_retained_facility_all_five_enrichment_fields_lost(self):
        new = copy.deepcopy(self.base)
        for field in ("description", "website", "insurance", "enriched_at", "enrichment_confidence"):
            new[0].pop(field)
        with self.assertRaisesRegex(ValueError, "ENRICHMENT"):
            validate(self.base, new)

    def test_enriched_identity_removed_not_replaced_by_new_enrichment(self):
        new = copy.deepcopy(self.base)
        new[0] = record(20000)
        with self.assertRaisesRegex(ValueError, "ENRICHMENT.*missing"):
            validate(self.base, new)

    def test_future_enrichment_field_loss_refused(self):
        base = copy.deepcopy(self.base)
        base[0]["verified_program_details"] = {"source": "fixture", "programs": ["verified"]}
        with self.assertRaisesRegex(ValueError, "ENRICHMENT.*verified_program_details"):
            validate(base, self.base)

    def test_cli_refusal_nonzero_and_no_stale_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "base.json").write_text(json.dumps(self.base))
            new = copy.deepcopy(self.base)
            new[-1] = copy.deepcopy(new[0])
            (tmp / "new.json").write_text(json.dumps(new))
            (tmp / "summary.json").write_text('{"facilities":10000}')
            result = subprocess.run([sys.executable, "-B", str(SCRIPTS / "validate_refresh.py"),
                                     str(tmp / "base.json"), str(tmp / "new.json"), str(tmp / "summary.json")],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("GATE FAILED", result.stdout)
            self.assertFalse((tmp / "summary.json").exists())


def enrichment_negative(field):
    def check(self):
        new = copy.deepcopy(self.base)
        new[0].pop(field)
        with self.assertRaisesRegex(ValueError, "ENRICHMENT"):
            validate(self.base, new)
        new = copy.deepcopy(self.base)
        new[0][field] = [] if field == "insurance" else "Changed value"
        with self.assertRaisesRegex(ValueError, "ENRICHMENT"):
            validate(self.base, new)
    return check


for field in ("description", "website", "insurance", "enriched_at", "enrichment_confidence"):
    setattr(Gates, "test_retained_" + field + "_loss_or_mutation", enrichment_negative(field))


class Merge(unittest.TestCase):
    def test_incoming_identical_duplicates_dropped(self):
        incoming = [record(0), record(1), record(0)]
        merged, _ = refresh.merge_records([record(0), record(1)], incoming)
        self.assertEqual(len(merged), 2)

    def test_conflicting_incoming_duplicate_refused(self):
        incoming = [record(0), record(0)]
        incoming[1]["website"] = "https://conflict.invalid"
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            deduplicate(incoming)

    def test_carry_without_marker_and_future_fields(self):
        old = record(0)
        old.pop("enriched_at")
        old["verified_program_details"] = {"value": [1, 2]}
        fresh = record(0)
        for f in ("description", "website", "insurance", "enrichment_confidence"):
            fresh.pop(f)
        merged, _ = refresh.merge_records([old], [fresh])
        for f in ("description", "website", "insurance", "enrichment_confidence", "verified_program_details"):
            self.assertEqual(merged[0][f], old[f])

    def test_full_main_dedup_preservation_with_no_guard(self):
        base = [record(i) for i in range(10000)]
        base[-1]["curated"] = True
        rows = [{"name1": r["name"], "city": r["city"], "state": r["stateAbbr"],
                 "latitude": r["latitude"], "longitude": r["longitude"], "typeFacility": "SA"}
                for r in base]
        rows.append(copy.deepcopy(rows[0]))
        for guard in (None, "0", "1"):
            with self.subTest(guard=guard), tempfile.TemporaryDirectory() as tmp:
                file = Path(tmp) / "facilities.json"
                file.write_text(json.dumps(base))
                def fetch(page):
                    return {"recordCount": len(rows), "rows": rows[(page-1)*1000:page*1000]}
                with patch.object(refresh, "REPO_ROOT", tmp), patch.object(refresh, "FACILITIES_PATH", str(file)), \
                     patch.object(refresh, "fetch_page", fetch), patch.object(refresh.urllib.request, "urlopen", forbidden), \
                     patch.dict(os.environ, {}, clear=True), patch("sys.stdout", new_callable=io.StringIO):
                    if guard is not None:
                        os.environ["REFRESH_NO_MODEL"] = guard
                    refresh.main()
                merged = json.loads(file.read_text())
                self.assertEqual(len(merged), 10000)
                self.assertEqual(validate(base, merged)["facilities"], 10000)
                self.assertTrue((Path(tmp) / "enrichment-queue.json").exists())

    def test_truncated_fetch_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "facilities.json"
            file.write_text(json.dumps([record(0)]))
            original = file.read_bytes()
            with patch.object(refresh, "REPO_ROOT", tmp), patch.object(refresh, "FACILITIES_PATH", str(file)), \
                 patch.object(refresh, "fetch_page", return_value={"recordCount": 10000, "rows": []}):
                with self.assertRaisesRegex(ValueError, "COMPLETION"):
                    refresh.main()
            self.assertEqual(file.read_bytes(), original)
            self.assertFalse((Path(tmp) / "enrichment-queue.json").exists())

    def test_ambiguous_merge_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "facilities.json"
            file.write_text(json.dumps([record(0), record(0)]))
            original = file.read_bytes()
            with patch.object(refresh, "FACILITIES_PATH", str(file)), patch.object(refresh, "fetch_page", forbidden):
                with self.assertRaisesRegex(ValueError, "IDENTITY"):
                    refresh.main()
            self.assertEqual(file.read_bytes(), original)

    def test_net_new_is_only_queued(self):
        merged, queue = refresh.merge_records([record(0)], [record(0), record(1)])
        self.assertEqual(len(merged), 2)
        self.assertEqual([r["reason"] for r in queue], ["net-new"])

    def test_no_model_or_search_call_source_and_negative_detector(self):
        prohibited = ("api.anthropic.com", "google.serper.dev", "haiku_enrich", "serper_search", "enrich_batch")
        def clean(source):
            return not any(token in source for token in prohibited)
        for name in ("refresh-samhsa.py", "refresh_identity.py", "validate_refresh.py", "pages_refresh.py"):
            self.assertTrue(clean((SCRIPTS / name).read_text(encoding="utf-8")), name)
        self.assertFalse(clean('urllib.request.urlopen("https://api.anthropic.com/v1/messages")'))


class FakeClient:
    def __init__(self, plan):
        self.plan = plan
        self.id = plan["prior"]
        self.live_count = plan["before_count"]
        self.sha = "committed-sha"
        self.rollback_calls = []
        self.rollback_error = False
        self.restore_count = True
        self.restore_id = True
        self.bad_detail = False

    def canonical(self):
        return {"id": self.id, "environment": "production", "latest_stage": {"status": "success"},
                "deployment_trigger": {"metadata": {"commit_hash": self.sha, "branch": "main"}}}

    def count(self):
        return self.live_count

    def detail(self, r):
        if self.bad_detail:
            return "**" + r["name"][:10] + "**\nLocation: Other City, Illinois\n"
        return "**" + r["name"] + "**\nLocation: " + r["city"] + ", " + r["state"] + "\nPhone: fixture\n"

    def rollback(self, prior):
        self.rollback_calls.append(prior)
        if self.rollback_error:
            raise RuntimeError("Rollback API refused request")
        if self.restore_id:
            self.id = prior
        if self.restore_count:
            self.live_count = self.plan["before_count"]


class Deployment(unittest.TestCase):
    def setUp(self):
        self.plan = {"prior": "prior-deployment", "before_count": 10001,
                     "expected_count": 10000, "spots": [record(i) for i in range(3)]}
        self.client = FakeClient(self.plan)
        self.receipt = {}

    def run_rail(self, deploy):
        pages.deploy_and_verify(self.client, self.plan, "committed-sha", deploy,
                                self.receipt, sleep=lambda _: None)

    def deploy(self):
        self.client.id = "new-deployment"
        self.client.live_count = 10000

    def assert_rollback(self, deploy):
        with self.assertRaisesRegex(RuntimeError, "restored and verified"):
            self.run_rail(deploy)
        self.assertEqual(self.client.rollback_calls, ["prior-deployment"])
        self.assertEqual(self.receipt["rollback"]["count"], 10001)
        self.assertEqual(self.receipt["status"], "DEPLOY_OR_READBACK_FAILED")

    def test_positive_readback_records_new_id(self):
        self.run_rail(self.deploy)
        self.assertEqual(self.receipt["after"]["deployment"], "new-deployment")
        self.assertEqual(self.receipt["observed_canonical_deployment"], "new-deployment")
        self.assertEqual(self.client.rollback_calls, [])

    def test_deploy_step_failure_also_rolls_back(self):
        def deploy_failure():
            self.deploy()
            raise subprocess.CalledProcessError(1, "wrangler")
        self.assert_rollback(deploy_failure)

    def test_deploy_timeout_also_rolls_back(self):
        def deploy_timeout():
            self.deploy()
            raise subprocess.TimeoutExpired("wrangler", 600)
        self.assert_rollback(deploy_timeout)

    def test_endpoint_count_mismatch_rolls_back_and_returns_failure(self):
        def mismatch():
            self.deploy()
            self.client.live_count = 9999
        self.assert_rollback(mismatch)
        self.assertEqual(self.receipt["observed_canonical_deployment"], "new-deployment")

    def test_arbitrary_partial_or_wrong_location_spot_rejected(self):
        self.client.bad_detail = True
        self.assert_rollback(self.deploy)

    def test_no_new_deployment_id_rejected(self):
        def stale():
            self.client.live_count = 10000
        self.assert_rollback(stale)

    def test_wrong_canonical_commit_rejected(self):
        self.client.sha = "other-sha"
        self.assert_rollback(self.deploy)

    def test_wrong_canonical_branch_rejected(self):
        original = self.client.canonical
        def preview():
            result = original()
            result["deployment_trigger"]["metadata"]["branch"] = "other-branch"
            return result
        with patch.object(self.client, "canonical", preview):
            self.assert_rollback(self.deploy)

    def test_rollback_api_failure_is_not_reported_as_success(self):
        self.client.rollback_error = True
        self.client.bad_detail = True
        with self.assertRaisesRegex(RuntimeError, "NOT verified"):
            self.run_rail(self.deploy)
        self.assertIn("rollback_failure", self.receipt)
        self.assertNotIn("rollback", self.receipt)

    def test_rollback_wrong_count_is_not_reported_as_success(self):
        self.client.restore_count = False
        self.client.bad_detail = True
        with self.assertRaisesRegex(RuntimeError, "NOT verified"):
            self.run_rail(self.deploy)
        self.assertNotIn("rollback", self.receipt)

    def test_rollback_wrong_id_is_not_reported_as_success(self):
        self.client.restore_id = False
        self.client.bad_detail = True
        with self.assertRaisesRegex(RuntimeError, "NOT verified"):
            self.run_rail(self.deploy)
        self.assertNotIn("rollback", self.receipt)

    def test_stale_before_state_prevents_deploy(self):
        self.client.id = "unexpected-before"
        with self.assertRaisesRegex(RuntimeError, "Stale"):
            self.run_rail(forbidden)
        self.assertEqual(self.client.rollback_calls, [])

    def test_three_main_only_spots_proved_absent_not_arbitrary(self):
        records = [record(i) for i in range(6)]
        missing = {r["name"] for r in records[3:]}
        spots = pages.select_spots(records, lambda r: "No facility found matching fixture" if r["name"] in missing else "present")
        self.assertEqual({r["name"] for r in spots}, missing)
        with self.assertRaisesRegex(RuntimeError, "three main-only"):
            pages.select_spots(records, lambda _: "present")

    def test_main_only_probe_budget_fails_closed(self):
        calls = []
        def present(r):
            calls.append(r)
            return "present"
        with self.assertRaises(RuntimeError):
            pages.select_spots([record(i) for i in range(100)], present, limit=60)
        self.assertEqual(len(calls), 60)

    def test_prepare_refuses_changed_before_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "facilities.json"
            path.write_text(json.dumps([record(i) for i in range(3)]))
            with patch.object(self.client, "detail", return_value="No facility found matching fixture"), \
                 patch.object(self.client, "count", side_effect=[10001, 10002]):
                with self.assertRaisesRegex(RuntimeError, "changed"):
                    pages.prepare(self.client, path)


class Transport(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"PROJECT": "fixture-project", "CLOUDFLARE_ACCOUNT_ID": "fixture-account",
                                           "CLOUDFLARE_API_TOKEN": "fixture-token-not-a-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = pages.Client()

    def test_api_success_false_even_http_200_refused(self):
        with patch.object(pages.urllib.request, "urlopen", return_value=io.BytesIO(b'{"success":false,"result":{"id":"prior"}}')):
            with self.assertRaisesRegex(RuntimeError, "refused"):
                self.client.rollback("prior")

    def test_api_wrong_rollback_id_refused(self):
        with patch.object(pages.urllib.request, "urlopen", return_value=io.BytesIO(b'{"success":true,"result":{"id":"wrong"}}')):
            with self.assertRaisesRegex(RuntimeError, "recorded prior id"):
                self.client.rollback("prior")

    def test_missing_or_failed_canonical_refused(self):
        for result in ({}, {"canonical_deployment": {"id": "prior", "environment": "preview", "latest_stage": {"status": "success"}}},
                       {"canonical_deployment": {"id": "prior", "environment": "production", "latest_stage": {"status": "failure"}}}):
            with self.subTest(result=result), patch.object(self.client, "api", return_value=result):
                with self.assertRaises(RuntimeError):
                    self.client.canonical()

    def test_logged_out_public_transport(self):
        seen = []
        def answer(req, **kwargs):
            seen.append(req)
            return io.BytesIO(b'{"result":{"content":[{"type":"text","text":"(10000 total)"}]}}')
        with patch.object(pages.urllib.request, "urlopen", answer):
            self.assertEqual(self.client.count(), 10000)
        self.assertFalse(any(k.lower() in ("authorization", "cookie", "x-api-key") for k in seen[0].headers))
        self.assertNotIn("fixture-token-not-a-secret", seen[0].data.decode())

    def test_public_error_or_unparseable_count_refused(self):
        for value in (b'{"error":{"message":"refused"}}', b'{"result":{"isError":true}}',
                      b'{"result":{"content":[{"type":"text","text":"no count"}]}}'):
            with self.subTest(value=value), patch.object(pages.urllib.request, "urlopen", return_value=io.BytesIO(value)):
                with self.assertRaises(RuntimeError):
                    self.client.count()


class Wiring(unittest.TestCase):
    def test_workflow_gates_precede_and_condition_commit_and_deploy(self):
        source = (SCRIPTS.parent / ".github/workflows/samhsa-monthly-refresh.yml").read_text()
        self.assertLess(source.index("id: gates"), source.index("id: commit"))
        self.assertLess(source.index("id: commit"), source.index("id: main"))
        self.assertLess(source.index("id: main"), source.index("id: deploy"))
        for step, end in (("id: commit", "- name: Build"), ("id: deploy", "- name: Retain")):
            block = source[source.index(step):source.index(end)]
            self.assertIn("if: success() && steps.gates.outcome == 'success'", block)
            self.assertNotIn("continue-on-error", block)
        self.assertNotIn("continue-on-error", source)
        self.assertIn("git show HEAD:facilities.json", source)
        self.assertIn("git push origin HEAD:main", source)
        self.assertNotIn("--force", source)
        self.assertIn('test "$(git rev-parse origin/main)" = "$SHA"', source)
        self.assertIn("git worktree add --detach", source)
        self.assertIn("17 8 1 * *", source)
        self.assertIn("ref: main", source)
        self.assertIn("default: dry-run", source)
        self.assertEqual(source.count("secrets."), 2)

    def test_deploy_cli_checks_clean_sha_and_digest_before_wrangler(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            data = json.dumps([record(i) for i in range(3)]).encode()
            (tmp / "facilities.json").write_bytes(data)
            plan = {**{"prior": "prior", "before_count": 3, "expected_count": 3, "spots": []},
                    "facilities_sha256": pages.digest(tmp / "facilities.json")}
            (tmp / "plan.json").write_text(json.dumps(plan))
            argv = ["pages_refresh.py", "deploy", "--plan", str(tmp / "plan.json"),
                    "--facilities", str(tmp / "facilities.json"), "--sha", "sha", "--receipt", str(tmp / "receipt.json")]
            for outputs in (["wrong-sha\n", "", data], ["sha\n", " M facilities.json", data],
                            ["sha\n", "", b"wrong committed bytes"]):
                with self.subTest(outputs=outputs[:2]), patch.object(sys, "argv", argv), \
                     patch.object(pages, "Client", return_value=None), \
                     patch.object(pages.subprocess, "check_output", side_effect=outputs), \
                     patch.object(pages.subprocess, "run", forbidden):
                    with self.assertRaisesRegex(RuntimeError, "clean committed main"):
                        pages.main()
            (tmp / "facilities.json").write_text("[]")
            with patch.object(sys, "argv", argv), patch.object(pages, "Client", return_value=None), \
                 patch.object(pages.subprocess, "run", forbidden):
                with self.assertRaisesRegex(RuntimeError, "bound"):
                    pages.main()


if __name__ == "__main__":
    unittest.main()
