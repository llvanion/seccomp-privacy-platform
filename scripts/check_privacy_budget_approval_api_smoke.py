#!/usr/bin/env python3
"""Smoke-test privacy-budget approval operator API endpoints."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def request_json(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    token: str = "",
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return int(resp.status), payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        payload = json.loads(raw) if raw else {"error": "empty_error_response"}
        return int(exc.code), payload


def wait_ready(base_url: str, *, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            status, payload = request_json("GET", f"{base_url}/healthz", timeout=0.5)
            if status == 200 and payload.get("status") == "ok":
                return
            last = f"{status} {payload}"
        except Exception as exc:  # noqa: BLE001
            last = repr(exc)
        time.sleep(0.1)
    raise RuntimeError(f"operator dashboard did not become ready: {last}")


def init_metadata_db(db_path: Path) -> None:
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(REPO_ROOT / 'scripts')!r});"
        "from metadata_db import connect_db, apply_migrations;"
        f"conn=connect_db({str(db_path)!r});"
        "apply_migrations(conn);"
        "conn.executescript('''"
        "INSERT OR IGNORE INTO tenants(tenant_id,created_at_utc,source,last_seen_job_id) "
        "VALUES('privacy_tenant','2026-06-01T00:00:00Z','privacy_budget_approval_api_smoke',NULL);"
        "INSERT OR IGNORE INTO callers(caller,tenant_id,created_at_utc,source,last_seen_job_id) "
        "VALUES('privacy_requester','privacy_tenant','2026-06-01T00:00:00Z','privacy_budget_approval_api_smoke',NULL);"
        "INSERT OR IGNORE INTO callers(caller,tenant_id,created_at_utc,source,last_seen_job_id) "
        "VALUES('privacy_operator','privacy_tenant','2026-06-01T00:00:00Z','privacy_budget_approval_api_smoke',NULL);"
        "INSERT OR IGNORE INTO caller_identities(caller,issuer,subject,subject_type,service_id,display_name,platform_roles_json,enabled,metadata_json,source,created_at_utc) "
        "VALUES('privacy_requester','local','user:requester','user',NULL,'Privacy Requester','[\"query_submitter\",\"privacy_operator\"]',1,'{}','privacy_budget_approval_api_smoke','2026-06-01T00:00:00Z');"
        "INSERT OR IGNORE INTO caller_identities(caller,issuer,subject,subject_type,service_id,display_name,platform_roles_json,enabled,metadata_json,source,created_at_utc) "
        "VALUES('privacy_operator','local','user:operator','user',NULL,'Privacy Operator','[\"privacy_operator\"]',1,'{}','privacy_budget_approval_api_smoke','2026-06-01T00:00:00Z');"
        "''');"
        "conn.commit(); conn.close()"
    )
    subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT), check=True)


def approval_request(request_id: str, *, caller: str = "privacy_requester", job_id: str = "privacy-job") -> dict[str, Any]:
    return {
        "schema": "privacy_budget_approval_request/v1",
        "created_at_utc": "2026-06-01T00:00:00Z",
        "status": "pending_approval",
        "request_id": request_id,
        "policy_version": "privacy-budget-api-smoke",
        "job_id": job_id,
        "correlation_id": f"corr-{job_id}",
        "caller": caller,
        "tenant_id": "privacy_tenant",
        "dataset_id": "orders_2026",
        "purpose": "attribution-release",
        "decision": "deny",
        "reason_code": "privacy_budget_near_duplicate",
        "reason": "near duplicate query requires manual review",
        "abuse_signal": "near_duplicate_or_differencing",
        "matched_prior_fingerprint": "prior-fingerprint",
        "matched_prior_job_id": "prior-job",
        "matched_prior_relation": "overlaps",
        "query_fingerprint": f"query-{request_id}",
        "query_payload_sha256": "a" * 64,
        "window": {
            "start": "2026-01-15T00:00:00Z",
            "end": "2026-02-15T00:00:00Z"
        },
        "bucket": "campaign-a",
        "value_mode": "raw-int",
        "threshold_k": 1,
        "budget": {
            "limit": 3,
            "cost": 1,
            "used_before": 1,
            "used_after": 1,
            "consumed": False
        },
        "parsed_metrics": {
            "intersection_size": 2,
            "intersection_sum": 425
        },
        "public_report_sha256": "b" * 64,
        "approval_recommendation": "manual_review_required"
    }


def write_queue(path: Path) -> None:
    rows = [
        approval_request("pba_111111111111111111111111", job_id="approve-job"),
        approval_request("pba_222222222222222222222222", job_id="reject-job"),
        approval_request("pba_333333333333333333333333", job_id="expire-job"),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-test privacy budget approval operator API")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata_db = out_dir / "metadata.sqlite"
    budget_store = out_dir / "budget.sqlite"
    queue_path = out_dir / "approval_queue.jsonl"
    decisions_path = out_dir / "approval_decisions.jsonl"
    for artifact in (metadata_db, budget_store, queue_path, decisions_path):
        for candidate in (artifact, Path(str(artifact) + "-wal"), Path(str(artifact) + "-shm")):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
    init_metadata_db(metadata_db)
    write_queue(queue_path)

    token_config = out_dir / "identity_tokens.json"
    requester_env = "PRIVACY_BUDGET_APPROVAL_API_SMOKE_REQUESTER_TOKEN"
    operator_env = "PRIVACY_BUDGET_APPROVAL_API_SMOKE_OPERATOR_TOKEN"
    requester_token = "privacy-budget-requester-token"
    operator_token = "privacy-budget-operator-token"
    write_json(
        token_config,
        {
            "schema": "api_identity_token_map/v1",
            "tokens": [
                {"token_env": requester_env, "issuer": "local", "subject": "user:requester"},
                {"token_env": operator_env, "issuer": "local", "subject": "user:operator"},
            ],
        },
    )

    port_code = (
        "import sys;"
        f"sys.path.insert(0, {str(REPO_ROOT / 'scripts')!r});"
        "from runtime_service_helpers import available_port;"
        "print(available_port())"
    )
    port = int(subprocess.check_output([sys.executable, "-c", port_code], cwd=str(REPO_ROOT), text=True).strip())
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env[requester_env] = requester_token
    env[operator_env] = operator_token
    env.pop("HTTP_PROXY", None)
    env.pop("http_proxy", None)
    out_base = out_dir / "dashboard_out"
    out_base.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "serve_operator_dashboard.py"),
            "--out-base", str(out_base),
            "--history-root", str(out_dir),
            "--bind-host", "127.0.0.1",
            "--port", str(port),
            "--metadata-db-path", str(metadata_db),
            "--identity-token-config", str(token_config),
            "--privacy-budget-store", str(budget_store),
            "--privacy-budget-approval-queue", str(queue_path),
            "--privacy-budget-approval-decisions", str(decisions_path),
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_ready(base_url)
        status, health = request_json("GET", f"{base_url}/healthz")
        if status != 200 or health.get("privacy_budget_approval_enabled") is not True:
            raise AssertionError(f"health did not expose approval API enabled: {status} {health}")

        list_status, pending = request_json(
            "GET",
            f"{base_url}/v1/privacy-budget/approvals?status=pending_approval",
            token=operator_token,
        )
        if list_status != 200 or pending.get("schema") != "privacy_budget_approval_list/v1":
            raise AssertionError(f"approval list failed: {list_status} {pending}")
        if pending.get("returned_count") != 3:
            raise AssertionError(f"expected 3 pending approvals, got {pending}")

        self_status, self_body = request_json(
            "POST",
            f"{base_url}/v1/privacy-budget/approval/pba_111111111111111111111111/approve",
            body={},
            token=requester_token,
        )
        if self_status != 403 or self_body.get("error") != "same_identity_self_approval":
            raise AssertionError(f"same-identity approve was not rejected: {self_status} {self_body}")

        approve_status, approve = request_json(
            "POST",
            f"{base_url}/v1/privacy-budget/approval/pba_111111111111111111111111/approve",
            body={"reason": "operator reviewed overlap", "expires_at_utc": "2026-12-31T00:00:00Z"},
            token=operator_token,
        )
        if approve_status != 200 or approve.get("decision", {}).get("status") != "approved":
            raise AssertionError(f"approval transition failed: {approve_status} {approve}")

        reject_missing_status, reject_missing = request_json(
            "POST",
            f"{base_url}/v1/privacy-budget/approval/pba_222222222222222222222222/reject",
            body={},
            token=operator_token,
        )
        if reject_missing_status != 400:
            raise AssertionError(f"reject without reason should fail: {reject_missing_status} {reject_missing}")

        reject_status, reject = request_json(
            "POST",
            f"{base_url}/v1/privacy-budget/approval/pba_222222222222222222222222/reject",
            body={"reason": "manual review rejected overlap"},
            token=operator_token,
        )
        if reject_status != 200 or reject.get("decision", {}).get("status") != "rejected":
            raise AssertionError(f"reject transition failed: {reject_status} {reject}")

        expire_status, expire = request_json(
            "POST",
            f"{base_url}/v1/privacy-budget/approval/pba_333333333333333333333333/expire",
            body={"reason": "review window expired"},
            token=operator_token,
        )
        if expire_status != 200 or expire.get("decision", {}).get("status") != "expired":
            raise AssertionError(f"expire transition failed: {expire_status} {expire}")

        decision_rows = load_jsonl(decisions_path)
        statuses = [row.get("status") for row in decision_rows]
        if statuses != ["approved", "rejected", "expired"]:
            raise AssertionError(f"unexpected decision log rows: {decision_rows}")

        approved_list_status, approved_list = request_json(
            "GET",
            f"{base_url}/v1/privacy-budget/approvals?status=approved",
            token=operator_token,
        )
        if approved_list_status != 200 or approved_list.get("returned_count") != 1:
            raise AssertionError(f"approved list failed: {approved_list_status} {approved_list}")

        report = {
            "schema": "privacy_budget_approval_api_smoke/v1",
            "status": "ok",
            "pending_count_before": pending.get("returned_count"),
            "approved_request_id": approve.get("request_id"),
            "rejected_request_id": reject.get("request_id"),
            "expired_request_id": expire.get("request_id"),
            "decision_statuses": statuses,
            "self_approval_status": self_status,
        }
        text = json.dumps(report, ensure_ascii=False, indent=2)
        (out_dir / "privacy_budget_approval_api_smoke.json").write_text(text + "\n", encoding="utf-8")
        (out_dir / "privacy_budget_approval_list.json").write_text(
            json.dumps(approved_list, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (out_dir / "privacy_budget_approval_transition.json").write_text(
            json.dumps(approve, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(text)
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
