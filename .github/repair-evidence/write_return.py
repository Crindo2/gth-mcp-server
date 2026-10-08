"""Write the mandated repair envelope and local byte-hash evidence, offline."""
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
REPO = ROOT / "repo"
EVIDENCE = REPO / ".github/repair-evidence"
NOW = datetime.now(timezone.utc).isoformat()
git = ["git", "--no-optional-locks", "-c", "safe.directory=" + REPO.as_posix(), "-C", str(REPO)]
head = subprocess.check_output(git + ["rev-parse", "HEAD"]).decode().strip()
assert head == "2350609474fe56134793d203860053f1d7d35632", "Unexpected subject HEAD"
tests = (EVIDENCE / "offline-tests.txt").read_text(encoding="utf-8")
assert "Ran 51 tests" in tests and tests.rstrip().endswith("OK")
fixtures = json.loads((EVIDENCE / "prior-fixture-recheck.json").read_text())
assert len(fixtures) == 11 and all(r["matched_expectation"] for r in fixtures)
baseline = json.loads((EVIDENCE / "production-baseline-check.json").read_text())
assert baseline["accepted"] is False and baseline["duplicate_stable_identity_groups"] == 55
assert subprocess.run(git + ["diff", "--check"], capture_output=True).returncode == 0

reasons = {
    "repo/.github/workflows/samhsa-monthly-refresh.yml": "Gates explicitly condition main commit/deploy; clean pinned main build; before/after receipts and failure-preserving checked rollback.",
    "repo/scripts/refresh-samhsa.py": "Remove all model/search implementations and guarded defaults; deduplicate incoming data, refuse ambiguities, preserve enrichment and produce a separate queue.",
    "repo/scripts/validate_refresh.py": "Reject duplicate/ambiguous identities and curated swaps, retain both completion limits, and compare enrichment values per retained facility; no passing summary on refusal.",
    "repo/scripts/refresh_identity.py": "Share identity matching, duplicate refusal and enrichment preservation between merge and validator, including future enrichment fields.",
    "repo/scripts/pages_refresh.py": "Prove main-only fixtures before deploy, bind logged-out count/detail read-back to clean committed data and new canonical main SHA, and validate rollback API/restoration after deploy or read-back failures.",
    "repo/scripts/tests/test_monthly_refresh.py": "51 offline tests covering every gate and fixed defect, with a live-network trap and mocked deployment/rollback lifecycle.",
    "repo/.github/repair-evidence/quoted-requirements.txt": "Verbatim governing instructions and all prior VERIFY_FAIL findings captured before runtime edits; no person identifiers.",
    "repo/.github/repair-evidence/offline-tests.txt": "Saved passing 51-test execution output, including named negative controls.",
    "repo/.github/repair-evidence/prior-fixture-recheck.json": "Re-run all 11 supplied prior verifier gate fixtures against repaired validator; record expectations, outcomes and fixture byte hashes.",
    "repo/.github/repair-evidence/production-baseline-check.json": "Record production base SHA/count and honest failure on existing duplicate identities, without copying facility identifiers.",
    "repo/.github/repair-evidence/repair-report.txt": "Repair coverage, independent-verification boundary, baseline activation blocker and ready reconciliation draft.",
    "repo/.github/repair-evidence/write_return.py": "Reproduce the mandatory Python json.dump envelope and byte-hash evidence, without any external operation.",
    "repo/.github/repair-evidence/change-manifest.json": "Machine-readable list of every changed repository path and its one-line reason; bind all other changed bytes.",
}

report = """GetTreatmentHelp's monthly rail now refuses the reproduced unsafe candidates before commit/deploy, preserves retained enrichment, and returns failure after deployment/read-back errors even when checked rollback succeeds. This repair requires fresh non-author verification; it is not a merge or live-readiness verdict.

Scope: bounded repair of PR #2 on lane/samhsa-monthly-github-actions, unchanged detached HEAD 2350609474fe56134793d203860053f1d7d35632. Every runtime edit remains uncommitted. Governing C716 s.1-s.3 and all prior defects are quoted verbatim in quoted-requirements.txt, captured before runtime edits. The operative requirements take precedence; no distribution or monetization demand was introduced.

Defect 1, identity: shared full identity combines normalized name/state/city with finite rounded coordinates. Distinct co-located facilities and separate branches remain distinct; exact duplicates fail the validator. Identical source duplicates are removed before merge; conflicting duplicates, divergent aliases, non-reciprocal matches and many-to-one matches fail closed. Prior curated identities and values are protected, rather than only comparing curated counts. All required identity fields must be present. An ambiguous prior dataset is refused before fetch or writes.

Defect 2, enrichment: every populated description, website, insurance, enriched_at and enrichment_confidence value is carried forward and checked against the same retained identity. Future fields outside the source schema are also preserved and checked. A populated enrichment marker is not required to protect existing values. Enriched prior identities cannot disappear behind replacement records' aggregate counts. The earlier aggregate non-regression checks remain as secondary controls.

Completion: both >=10,000 and >=98% of the original committed prior count are required, using exact integer arithmetic. Fetch pages also require a consistent declared recordCount and refuse truncation. No failed validator run leaves a passing summary. Restore mode also runs the gates; dry-run never reaches live preflight, commit or deploy.

Defect 5, model code: all model/search implementations, imports, credentials, pricing and opt-in default paths were removed from the refresh script. It only fetches SAMHSA, normalizes, deduplicates and merges, then writes candidate data and a separate enrichment queue. Pipeline controls pass with the former guard absent, 0 and 1, while live-network calls are trapped.

Defect 6, C716 read-back: preflight records prior canonical deployment and logged-out count, proves absence of three unambiguous committed-candidate facilities on the prior live endpoint, and rechecks before-state stability. It fails closed if three main-only fixtures cannot be proved within the public request budget. After gates, the workflow commits only to main with a non-force push, records its SHA, checks origin/main is still exactly that SHA, and deploys a separate clean detached checkout. Candidate bytes must match both the preflight digest and that SHA's committed facilities.json. The after-read checks the new successful production canonical deployment's main branch/commit metadata, records its id even when later checks fail, compares the unauthenticated endpoint count to the committed count, and reads the exact full name and location of the three proved fixtures. No arbitrary substitutes are used.

Defect 7, rollback: the same tested lifecycle catches deploy command nonzero exits, deploy timeouts and all read-back failures. It promotes the recorded prior deployment, checks API success/result id, and polls authenticated canonical id plus logged-out public count until both match the before-state. A restoration failure is explicitly reported; a successful rollback still leaves the job failed. Before/after and rollback receipts are written in a finally block and retained with an always() artifact step.

Validation: python -B -m unittest discover -s scripts/tests -v passed all 51 tests. All 11 saved prior verifier gate fixtures now match their expected outcomes, including refusal of the former duplicate and per-facility enrichment-loss passes. Python sources parsed successfully; git diff --check passed. Tests exercise actual merge/main and validator code plus mocked Pages transports and lifecycle; workflow ordering/conditions were inspected by tests. No YAML library was available, so GitHub's own parser/runtime is not claimed verified.

MATERIAL ACTIVATION BLOCKER: origin/main at 4d611fc89fe319c93b678c691ccbb8f1d8c730a2 contains 12,362 records and 55 duplicate full identity groups (96 excess records; 22 groups are byte-equivalent record values). The unchanged committed set fails at duplicate records 259 and 260. The repaired rail will refuse this base instead of silently selecting or discarding enrichment. Production facilities.json was not changed. This blocker is separate from the reproduced code defects and must be resolved before the monthly rail can run successfully. If fewer than three main-only facilities can be proved, deployment preflight also refuses honestly.

Ready reconciliation draft: Reconcile the repeated committed identities in a separate bounded data repair using source evidence. Retain independently supported co-located programs or branches as distinct identities, and preserve all existing enrichment values. Collapse only demonstrated duplicates whose protected values agree; return conflicting descriptions, insurance or other factual treatments for the governing editorial decision instead of selecting a winner automatically. Validate the resulting committed baseline against identity, both completion thresholds and enrichment non-regression, then submit the rail repair for fresh non-author re-verification and merge_gate. Keep the Windows task Disabled throughout.

Boundary: Only BRIEF.md, PROGRAM-RECORD.json and the listed ref/vault/repo inputs were used. Local offline code repair and synthetic/mock execution only. No network, secret read, commit, push, merge, deploy, publish, send, database/production write or spend occurred. Neither live SAMHSA completeness, live endpoint/count, Pages permissions or behavior, GitHub parser/execution nor Windows task state was verified. No owner/editorial decision was taken. Runtime edits and evidence remain inside repo; only the mandated return envelope is written outside it.
"""
(EVIDENCE / "repair-report.txt").write_text(report, encoding="utf-8", newline="\n")

changed = sorted(reasons)
actual = sorted("repo/" + line for line in subprocess.check_output(
    git + ["ls-files", "--modified", "--others", "--exclude-standard"]).decode().splitlines())
# The manifest is created below, so it may not yet appear on the first run.
assert set(actual) | {"repo/.github/repair-evidence/change-manifest.json"} == set(changed), (actual, changed)

manifest = {"subject_head": head, "recorded_at": NOW, "changes": [
    {"path": path, "reason": reasons[path], "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}
    for path in changed if not path.endswith("change-manifest.json")
]}
manifest["inputs"] = [{"path": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}
                      for path in ("BRIEF.md", "PROGRAM-RECORD.json", "ref/verify-return/ALLOC-C716-GTHV-L117-225-return.json")]
(EVIDENCE / "change-manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=True), encoding="utf-8", newline="\n")

env = {
    "program_id": "GTH-SAMHSA-RAIL-PR2-VERIFY-01",
    "stage_id": "GTH-PR2-VERIFY-REPAIR-1",
    "allocation_id": "ALLOC-C723-GTHR-L117-249",
    "worker_id": "c723-gthr-l117-249",
    "result": "NEEDS_VERIFY",
    "summary": "GetTreatmentHelp's monthly refresh now refuses the reproduced duplicate and enrichment-loss candidates and has tested deployment read-back and checked rollback. All 51 offline tests and 11 prior verifier fixtures passed their expectations. The uncommitted repair needs fresh verification; activation is blocked by duplicate identities already committed in production main.",
    "property": "GTH: bounded repair of every PR #2 VERIFY_FAIL defect in the monthly SAMHSA workflow, refresh/merge, identity/completion/enrichment gates, main-only logged-out read-back and checked rollback, at unchanged detached subject HEAD 2350609474fe56134793d203860053f1d7d35632.",
    "boundary": "Only listed inputs; offline repair and synthetic/mock validation. No network, secret read, commit, push, merge, deploy, publish, send, production/database write or spend. Edits are uncommitted under repo. Does not verify live data, endpoints, Pages/GitHub execution or Windows task state. Existing production duplicate records were not adjudicated or changed. Fresh non-author verification and merge_gate remain required.",
    "blocker": "Production activation cannot pass the repaired identity gate until the 55 pre-existing duplicate stable-identity groups in origin/main are reconciled with enrichment preserved; unchanged 12,362-record base is refused. Code repair is ready for independent re-verification. Main-only preflight also refuses when three absent fixtures cannot be proved.",
    "material_exception": True,
    "findings": [
        "Quoted every prior VERIFY_FAIL finding verbatim before runtime repair; the governing C716 s.1-s.3 text and detailed defects are saved in repo/.github/repair-evidence/quoted-requirements.txt.",
        "Identity repair rejects duplicate/ambiguous and many-to-one identities, removes identical incoming SAMHSA duplicates, refuses conflicting duplicates, protects every curated identity/value, and keeps distinct co-located facilities or branches distinct.",
        "Enrichment repair preserves and verifies exact per-retained-facility values for description, website, insurance, enriched_at, enrichment_confidence and future enrichment fields, with and without enriched_at; enriched identity disappearance and aggregate losses also refuse.",
        "Completion retains both >=10,000 AND >=98% of the original prior committed count, inclusive at exactly 98%; malformed/truncated or changing-count fetches refuse. Every failed gate blocks commit/deploy and leaves no passing summary.",
        "Callable model/search code and the unguarded enrichment default were removed entirely from the refresh script; a separate queue remains and no enrichment credential is used on the rail.",
        "C716 before/after repair proves three main-only fixtures absent before deployment, binds count/data to clean committed main SHA, captures/checks the new canonical production deployment id and main commit metadata, and checks exact logged-out facility names/locations.",
        "Deploy command failure, timeout and read-back failure all enter checked rollback; API success and prior id are checked, canonical id and logged-out count must restore the before-state, and successful rollback still returns failure.",
        "PASS: 51 offline tests under a live-network trap; PASS: all 11 original verifier fixtures match expected outcomes; Python sources parsed and git diff --check passed. No live or GitHub runtime claim is made.",
        "MATERIAL ACTIVATION BLOCKER: production origin/main 4d611fc89fe319c93b678c691ccbb8f1d8c730a2 has 55 duplicate stable-identity groups and 96 excess records; the unchanged 12,362-record base is refused at records 259/260. No production facility data was altered.",
        "Ready reconciliation draft: Resolve repeated committed identities as a separate bounded source-backed data repair. Preserve independently supported co-located programs/branches and all enrichment; collapse only demonstrated duplicates with agreeing protected values. Return conflicts in factual treatment for the governing editorial decision rather than choosing a winner automatically. Gate the repaired committed base, then complete fresh non-author rail verification and merge_gate; keep the Windows task Disabled.",
        "Preflight fails closed if it cannot prove three main-only fixtures within 60 public detail probes. Live source completeness, endpoint state, GitHub parser/execution, Cloudflare rollback behavior/permissions and Disabled Windows task state remain unverified offline.",
    ] + [path + ": " + reasons[path] for path in changed],
    "changed_paths": changed,
    "evidence": [{"path": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
                  "note": reasons[path] + " Local offline repair evidence recorded " + NOW + "; subject HEAD " + head + "."}
                 for path in changed],
    "actions_taken": [
        "Read PROGRAM-RECORD.json first, then the listed governing rulings and prior non-author VERIFY_FAIL; quoted the operative ruling and every defect before runtime edits.",
        "Repaired the three original artifacts and added shared identity rules, a Pages lifecycle helper and stdlib offline negative controls; left every change uncommitted.",
        "Ran the actual merge/main without the former no-model guard and with guard values 0/1, using mocked source pages and trapped live network; verified dedup, curated preservation and exact enrichment carry-forward.",
        "Ran all 51 offline tests and all 11 saved prior validator fixtures, including deployment failure/timeout, main-only read-back, API-level rollback failure and failed restoration controls.",
        "Checked the unchanged committed production baseline through the repaired validator and recorded its pre-existing duplicate-identity blocker without exposing facility identifiers or changing data.",
        "Recorded unchanged subject HEAD, parsed Python sources, passed git diff --check, enumerated every changed path and hashed all local evidence bytes.",
        "Wrote this exact mandatory return envelope with Python json.dump, indent=1, ensure_ascii=True and UTF-8 LF newlines; no external operation or commit occurred.",
    ],
}
p = ROOT / "_return/ALLOC-C723-GTHR-L117-249-return.json"
p.parent.mkdir(exist_ok=True)
json.dump(env, open(p, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=True)
print(json.dumps({"return_path": p.relative_to(ROOT).as_posix(), "result": env["result"],
                  "changed_paths": len(changed), "evidence_entries": len(env["evidence"])}, indent=1))
