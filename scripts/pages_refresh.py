#!/usr/bin/env python3
"""C716 before/after receipts and checked rollback. Credentials are env-only.

Public MCP requests use a separate, unauthenticated transport. The lifecycle is
dependency-injected for offline negative controls; its CLI is used by Actions.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Client:
    def __init__(self):
        self.project = os.environ["PROJECT"]
        account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
        self.base = ("https://api.cloudflare.com/client/v4/accounts/" + quote(account, safe="")
                     + "/pages/projects/" + quote(self.project, safe=""))
        self.endpoint = "https://" + self.project + ".pages.dev/mcp"

    def api(self, suffix="", method="GET"):
        req = urllib.request.Request(self.base + suffix, method=method,
                                     headers={"Authorization": "Bearer " + os.environ["CLOUDFLARE_API_TOKEN"]})
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.load(response)
        if result.get("success") is not True or result.get("errors"):
            raise RuntimeError("Pages API refused request")
        if not isinstance(result.get("result"), dict):
            raise RuntimeError("Pages API returned invalid result")
        return result["result"]

    def canonical(self):
        result = self.api().get("canonical_deployment")
        if not isinstance(result, dict) or not isinstance(result.get("id"), str) or not result["id"]:
            raise RuntimeError("Missing canonical deployment id")
        if result.get("environment") != "production" or result.get("latest_stage", {}).get("status") != "success":
            raise RuntimeError("Canonical deployment is not successful production")
        return result

    def call(self, name, args):
        # No credentials, cookies or authorization headers on public read-back.
        req = urllib.request.Request(self.endpoint, data=json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }).encode(), headers={"Content-Type": "application/json", "User-Agent": "gth-monthly-readback"})
        with urllib.request.urlopen(req, timeout=60) as response:
            body = json.load(response)
        result = body.get("result", {})
        if body.get("error") or result.get("isError"):
            raise RuntimeError("Public MCP read-back failed")
        content = result.get("content", [])
        if not content or content[0].get("type") != "text" or not isinstance(content[0].get("text"), str):
            raise RuntimeError("Invalid public MCP response")
        return content[0]["text"]

    def count(self):
        match = re.search(r"\((\d+) total\)", self.call("list_states", {}))
        if not match:
            raise RuntimeError("Public count missing")
        return int(match.group(1))

    def detail(self, record):
        return self.call("get_facility_detail", {"name": record["name"]})

    def rollback(self, deployment):
        result = self.api("/deployments/" + quote(deployment, safe="") + "/rollback", "POST")
        if result.get("id") != deployment:
            raise RuntimeError("Rollback API did not confirm the recorded prior id")


def select_spots(records, detail, limit=60):
    # Detail only supports name substring queries. Skip ambiguous queries, and
    # prove absence on the prior live set instead of selecting arbitrary records.
    names = [r["name"].casefold() for r in records]
    selected, calls = [], 0
    for record in sorted(records, key=lambda r: (r["name"], r["stateAbbr"], r["city"])):
        name = record["name"].casefold()
        if sum(name in n for n in names) != 1:
            continue
        calls += 1
        text = detail(record)
        if text.startswith("No facility found matching "):
            selected.append({k: record[k] for k in ("name", "city", "state", "stateAbbr")})
            if len(selected) == 3:
                return selected
        if calls >= limit:
            break
    raise RuntimeError("Read-back preflight: cannot prove three main-only facilities within public request budget")


def prepare(client, facilities):
    records = json.loads(Path(facilities).read_text(encoding="utf-8"))
    prior = client.canonical()["id"]
    before = client.count()
    spots = select_spots(records, client.detail)
    if client.canonical()["id"] != prior or client.count() != before:
        raise RuntimeError("Live state changed during before-read; no deployment allowed")
    # Completeness is also checked against what production serves now, not only against committed main.
    if len(records) < 0.98 * before:
        raise RuntimeError(f"Refreshed count {len(records)} is below 98% of the live public count {before}; no deployment allowed")
    return {"prior": prior, "before_count": before, "expected_count": len(records),
            "facilities_sha256": digest(facilities), "spots": spots,
            "recorded_at": datetime.now(timezone.utc).isoformat()}


def verify_after(client, plan, sha, receipt=None):
    current = client.canonical()
    if receipt is not None:
        receipt["observed_canonical_deployment"] = current["id"]
    metadata = current.get("deployment_trigger", {}).get("metadata", {})
    if current["id"] == plan["prior"] or metadata.get("commit_hash") != sha or metadata.get("branch") != "main":
        raise RuntimeError("New canonical deployment does not identify the committed main SHA")
    count = client.count()
    if count != plan["expected_count"]:
        raise RuntimeError(f"Public count mismatch: {count} != {plan['expected_count']}")
    if len(plan["spots"]) != 3:
        raise RuntimeError("Three proven main-only spot-reads required")
    for record in plan["spots"]:
        text = client.detail(record)
        expected = "**" + record["name"] + "**\nLocation: " + record["city"] + ", " + record["state"]
        if not text.startswith(expected + "\n"):
            raise RuntimeError("Public spot-read did not return the exact committed facility and location")
    if client.canonical()["id"] != current["id"]:
        raise RuntimeError("Canonical deployment changed during after-read")
    return {"deployment": current["id"], "count": count, "main_sha": sha, "spot_reads": 3}


def verify_rollback(client, plan):
    if client.canonical()["id"] != plan["prior"]:
        raise RuntimeError("Rollback did not restore the prior canonical deployment")
    if client.count() != plan["before_count"]:
        raise RuntimeError("Rollback did not restore the recorded public count")
    if client.canonical()["id"] != plan["prior"]:
        raise RuntimeError("Canonical deployment changed during rollback read-back")
    return {"deployment": plan["prior"], "count": plan["before_count"]}


def poll(check, sleep=time.sleep, attempts=3):
    for attempt in range(attempts):
        try:
            return check()
        except Exception:
            if attempt == attempts - 1:
                raise
            sleep(5)


def deploy_and_verify(client, plan, sha, deploy, receipt, sleep=time.sleep):
    # Exceptions after invoking wrangler include nonzero exit / timeout: Pages
    # may already have changed even when the deploy command reports failure.
    if client.canonical()["id"] != plan["prior"] or client.count() != plan["before_count"]:
        raise RuntimeError("Stale before-state; deployment refused")
    try:
        deploy()
        receipt["after"] = poll(lambda: verify_after(client, plan, sha, receipt), sleep)
        receipt["status"] = "READBACK_OK"
    except Exception as exc:
        receipt["status"] = "DEPLOY_OR_READBACK_FAILED"
        receipt["failure"] = type(exc).__name__
        try:
            client.rollback(plan["prior"])
            receipt["rollback"] = poll(lambda: verify_rollback(client, plan), sleep)
        except Exception as rollback_exc:
            receipt["rollback_failure"] = type(rollback_exc).__name__
            raise RuntimeError("Deployment/read-back failed; rollback restoration NOT verified") from rollback_exc
        raise RuntimeError("Deployment/read-back failed; prior deployment restored and verified") from exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "deploy"))
    parser.add_argument("--plan", required=True)
    parser.add_argument("--facilities", default="facilities.json")
    parser.add_argument("--sha")
    parser.add_argument("--receipt")
    args = parser.parse_args()
    client = Client()
    if args.action == "prepare":
        plan = prepare(client, args.facilities)
        Path(args.plan).write_text(json.dumps(plan, indent=1), encoding="utf-8")
        print(f"BEFORE: {plan['before_count']} facilities; canonical {plan['prior']}; three main-only fixtures proved absent")
        return
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if not args.sha or not args.receipt or digest(args.facilities) != plan["facilities_sha256"]:
        raise RuntimeError("Deployment data not bound to the before-read plan")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    committed = subprocess.check_output(["git", "show", args.sha + ":facilities.json"])
    if head != args.sha or dirty or hashlib.sha256(committed).hexdigest() != plan["facilities_sha256"]:
        raise RuntimeError("Deployment requires clean committed main data at the recorded SHA")
    receipt = {"before": plan, "main_sha": args.sha}
    try:
        deploy_and_verify(client, plan, args.sha, lambda: subprocess.run([
            "npx", "--yes", "wrangler@4.107.0", "pages", "deploy", ".",
            "--project-name=" + client.project, "--branch=main", "--commit-hash=" + args.sha,
            "--commit-dirty=false", "--commit-message=SAMHSA monthly deterministic rail",
        ], check=True, timeout=600), receipt)
    finally:
        Path(args.receipt).write_text(json.dumps(receipt, indent=1), encoding="utf-8")
        print(json.dumps(receipt, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not print HTTP bodies, URLs containing account ids, or credentials.
        print("Pages rail failed:", type(exc).__name__, str(exc) if isinstance(exc, RuntimeError) else "operation refused", file=sys.stderr)
        sys.exit(1)
