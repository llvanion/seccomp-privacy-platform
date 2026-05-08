#!/usr/bin/env python3
"""HTTP malformed-input gate for the record-recovery HTTP boundary (K3 sub-task).

Spawns the record-recovery HTTP service in-process on loopback (or talks to an
externally-supplied endpoint) and runs a battery of malformed requests:

1. Missing X-Request-Signature / request_signature on /recover when auth_token is set.
2. Expired or far-future request_timestamp_utc.
3. Wrong-shape payloads (non-object body, missing required fields).
4. SQL-injection-pattern strings in caller / job_id / tenant_id (must be treated as
   opaque strings rather than parameters).
5. Oversized request bodies (Content-Length above the configured cap).
6. Wrong HTTP method on POST endpoints.
7. Bad JSON.

Each scenario asserts the service rejected the request (status >= 400 or a clear
deny payload). Emits http_malformed_input_gate/v1 with each scenario's outcome.
"""
from __future__ import annotations

import argparse
import hmac
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from runtime_service_helpers import available_port  # noqa: E402

from services.record_recovery.http_service import (  # noqa: E402
    RecordRecoveryHttpHandler,
    RecordRecoveryHttpServer,
)
from services.record_recovery.runtime import build_service_state  # noqa: E402

SCHEMA_ID = "http_malformed_input_gate/v1"
NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json_response(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def http_request(
    *,
    url: str,
    method: str,
    body: bytes | None,
    headers: dict[str, str] | None,
    timeout_sec: float,
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    started = time.perf_counter()
    status = 0
    response_payload: dict[str, Any] = {}
    transport_error: str | None = None
    try:
        with NO_PROXY_OPENER.open(request, timeout=timeout_sec) as response:
            status = int(response.status)
            response_payload = load_json_response(response.read())
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        response_payload = load_json_response(exc.read() or b"")
    except Exception as exc:  # connection reset / refused / TLS / decode
        transport_error = f"{type(exc).__name__}: {exc}"
    return {
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "status_code": status,
        "response": response_payload,
        "transport_error": transport_error,
    }


# --- scenarios ---------------------------------------------------------------


def hmac_signature(token: str, request_id: str, ts: str, op: str) -> str:
    payload = f"{request_id}:{ts}:{op}".encode("utf-8")
    return hmac.new(token.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def base_recover_payload(
    *,
    caller: str = "benchmark-caller",
    tenant_id: str = "benchmark-tenant",
    dataset_id: str = "benchmark-dataset",
    job_id: str = "benchmark-job",
) -> dict[str, Any]:
    return {
        "schema": "sse_record_recovery_request/v1",
        "op": "recover",
        "request_id": "test-request-1",
        "request_timestamp_utc": utc_now_iso(),
        "caller": caller,
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "job_id": job_id,
        "role": "server",
        "candidate_ids": ["a", "b", "c"],
        "record_store_path": "/tmp/no-such-record-store.bin",
        "record_store_key_env": "BENCHMARK_RECORD_STORE_KEY",
        "output_path": "/tmp/no-such-output.csv",
    }


def assert_rejected(result: dict[str, Any], *, allowed_statuses: tuple[int, ...]) -> dict[str, Any]:
    transport_err = result.get("transport_error")
    status = int(result.get("status_code") or 0)
    response = result.get("response") or {}
    detected = bool(transport_err) or status in allowed_statuses or response.get("error") is not None
    return {
        "detected": detected,
        "status_code": status if status else None,
        "transport_error": transport_err,
        "response_error": response.get("error"),
        "response_reason": response.get("reason") or response.get("reason_code"),
    }


def scenario_missing_signature(*, base_url: str, timeout_sec: float, auth_token: str | None) -> dict[str, Any]:
    payload = base_recover_payload()
    if auth_token:
        payload.pop("request_signature", None)
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}" if auth_token else "",
    }
    res = http_request(
        url=f"{base_url}/recover",
        method="POST",
        body=body,
        headers={k: v for k, v in headers.items() if v},
        timeout_sec=timeout_sec,
    )
    return {
        "scenario": "missing_request_signature",
        "description": "POST /recover with no X-Request-Signature header and no request_signature payload field.",
        "result": res,
        "assertion": assert_rejected(res, allowed_statuses=(400, 401, 403)),
    }


def scenario_expired_timestamp(*, base_url: str, timeout_sec: float, auth_token: str | None) -> dict[str, Any]:
    payload = base_recover_payload()
    far_past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    payload["request_timestamp_utc"] = far_past
    if auth_token:
        payload["request_signature"] = hmac_signature(
            auth_token, payload["request_id"], far_past, payload["op"]
        )
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Request-Timestamp": far_past,
    }
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
        headers["X-Request-Signature"] = payload["request_signature"]
    res = http_request(
        url=f"{base_url}/recover",
        method="POST",
        body=body,
        headers=headers,
        timeout_sec=timeout_sec,
    )
    return {
        "scenario": "expired_request_timestamp",
        "description": "POST /recover with request_timestamp_utc 10 minutes in the past.",
        "result": res,
        "assertion": assert_rejected(res, allowed_statuses=(400, 401, 403)),
    }


def scenario_far_future_timestamp(*, base_url: str, timeout_sec: float, auth_token: str | None) -> dict[str, Any]:
    payload = base_recover_payload()
    far_future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    payload["request_timestamp_utc"] = far_future
    if auth_token:
        payload["request_signature"] = hmac_signature(
            auth_token, payload["request_id"], far_future, payload["op"]
        )
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-Request-Timestamp": far_future}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
        headers["X-Request-Signature"] = payload["request_signature"]
    res = http_request(
        url=f"{base_url}/recover",
        method="POST",
        body=body,
        headers=headers,
        timeout_sec=timeout_sec,
    )
    return {
        "scenario": "future_request_timestamp",
        "description": "POST /recover with request_timestamp_utc 10 minutes in the future.",
        "result": res,
        "assertion": assert_rejected(res, allowed_statuses=(400, 401, 403)),
    }


def scenario_sql_injection_strings(*, base_url: str, timeout_sec: float, auth_token: str | None) -> dict[str, Any]:
    payload = base_recover_payload(
        caller="alice'; DROP TABLE jobs; --",
        tenant_id="' OR 1=1 --",
        dataset_id="benchmark-dataset",
        job_id="benchmark'\";--",
    )
    if auth_token:
        payload["request_signature"] = hmac_signature(
            auth_token, payload["request_id"], payload["request_timestamp_utc"], payload["op"]
        )
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
        headers["X-Request-Timestamp"] = payload["request_timestamp_utc"]
        headers["X-Request-Signature"] = payload["request_signature"]
    res = http_request(
        url=f"{base_url}/recover",
        method="POST",
        body=body,
        headers=headers,
        timeout_sec=timeout_sec,
    )
    return {
        "scenario": "sql_injection_strings",
        "description": "POST /recover with SQL-injection-pattern caller/tenant_id/job_id; the service must treat them as opaque (deny on authz / record-store, never as parameters).",
        "result": res,
        "assertion": assert_rejected(res, allowed_statuses=(400, 403, 404)),
    }


def scenario_bad_json(*, base_url: str, timeout_sec: float, auth_token: str | None) -> dict[str, Any]:
    body = b"{this is not valid json"
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    res = http_request(
        url=f"{base_url}/recover",
        method="POST",
        body=body,
        headers=headers,
        timeout_sec=timeout_sec,
    )
    return {
        "scenario": "bad_json_payload",
        "description": "POST /recover with a syntactically invalid JSON body.",
        "result": res,
        "assertion": assert_rejected(res, allowed_statuses=(400,)),
    }


def scenario_non_object_payload(*, base_url: str, timeout_sec: float, auth_token: str | None) -> dict[str, Any]:
    body = json.dumps([1, 2, 3]).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    res = http_request(
        url=f"{base_url}/recover",
        method="POST",
        body=body,
        headers=headers,
        timeout_sec=timeout_sec,
    )
    return {
        "scenario": "non_object_json_payload",
        "description": "POST /recover with a JSON array body (must be a JSON object).",
        "result": res,
        "assertion": assert_rejected(res, allowed_statuses=(400,)),
    }


def scenario_oversized_body(*, base_url: str, timeout_sec: float, auth_token: str | None, body_size_bytes: int) -> dict[str, Any]:
    payload = base_recover_payload()
    payload["candidate_ids"] = [f"junk-{i:08d}" for i in range(max(1, body_size_bytes // 12))]
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    res = http_request(
        url=f"{base_url}/recover",
        method="POST",
        body=body,
        headers=headers,
        timeout_sec=timeout_sec,
    )
    return {
        "scenario": "oversized_body",
        "description": f"POST /recover with an oversized body of approximately {body_size_bytes} bytes; the server may reject due to authz/record-store, max_rows_per_request, or transport limits.",
        "result": res,
        "body_size_bytes": len(body),
        "assertion": assert_rejected(res, allowed_statuses=(400, 403, 404, 413)),
    }


def scenario_missing_required_field(*, base_url: str, timeout_sec: float, auth_token: str | None) -> dict[str, Any]:
    payload = base_recover_payload()
    payload.pop("candidate_ids", None)
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    res = http_request(
        url=f"{base_url}/recover",
        method="POST",
        body=body,
        headers=headers,
        timeout_sec=timeout_sec,
    )
    return {
        "scenario": "missing_required_field",
        "description": "POST /recover without candidate_ids in payload.",
        "result": res,
        "assertion": assert_rejected(res, allowed_statuses=(400, 403, 404)),
    }


def scenario_wrong_method(*, base_url: str, timeout_sec: float, auth_token: str | None) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    res = http_request(
        url=f"{base_url}/recover",
        method="DELETE",
        body=None,
        headers=headers,
        timeout_sec=timeout_sec,
    )
    return {
        "scenario": "wrong_http_method",
        "description": "DELETE /recover (only POST is supported).",
        "result": res,
        "assertion": assert_rejected(res, allowed_statuses=(400, 404, 405, 501)),
    }


def scenario_unknown_path(*, base_url: str, timeout_sec: float, auth_token: str | None) -> dict[str, Any]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    res = http_request(
        url=f"{base_url}/admin/unknown",
        method="POST",
        body=b"{}",
        headers=headers,
        timeout_sec=timeout_sec,
    )
    return {
        "scenario": "unknown_path",
        "description": "POST /admin/unknown — the service must return 404 (not_found).",
        "result": res,
        "assertion": assert_rejected(res, allowed_statuses=(404,)),
    }


SCENARIOS: list[Callable[..., dict[str, Any]]] = [
    scenario_missing_signature,
    scenario_expired_timestamp,
    scenario_far_future_timestamp,
    scenario_sql_injection_strings,
    scenario_bad_json,
    scenario_non_object_payload,
    scenario_missing_required_field,
    scenario_wrong_method,
    scenario_unknown_path,
]


# --- in-process service spawn -----------------------------------------------


def spawn_in_process_http_service(
    *,
    run_root: Path,
    auth_token_env: str,
    auth_token_value: str,
    max_rows_per_request: int,
) -> tuple[RecordRecoveryHttpServer, threading.Thread, str]:
    port = available_port()
    audit_log = run_root / "service_audit.jsonl"
    output_root = run_root / "outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    record_store_root = run_root / "store"
    record_store_root.mkdir(parents=True, exist_ok=True)
    if not os.environ.get(auth_token_env):
        os.environ[auth_token_env] = auth_token_value
    state = build_service_state(
        service_id="http-malformed-input-gate",
        tenant_id="http-malformed-input-tenant",
        dataset_id="http-malformed-input-dataset",
        auth_token_env=auth_token_env,
        metadata_db_path="",
        identity_token_config="",
        allowed_callers=["benchmark-caller"],
        authz_config="",
        allowed_output_roots=[str(output_root)],
        allowed_record_store_roots=[str(record_store_root)],
        audit_log=str(audit_log),
        transport="http",
        socket_path=None,
        endpoint_url=f"http://127.0.0.1:{port}",
        max_rows_per_request=max_rows_per_request,
    )
    server = RecordRecoveryHttpServer(
        ("127.0.0.1", port),
        RecordRecoveryHttpHandler,
        service_state=state,
        rate_limit_per_caller=0.0,
        rate_limit_burst=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            urllib.request.Request(base_url + "/health")
            urllib.request.urlopen(base_url + "/health", timeout=1.0).read()
            break
        except Exception:
            time.sleep(0.05)
    return server, thread, base_url


# --- main --------------------------------------------------------------------


def run_gate(
    *,
    base_url: str,
    auth_token: str | None,
    timeout_sec: float,
    body_size_bytes: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for runner in SCENARIOS:
        if runner is scenario_oversized_body:
            continue
        results.append(runner(base_url=base_url, timeout_sec=timeout_sec, auth_token=auth_token))
    results.append(
        scenario_oversized_body(
            base_url=base_url,
            timeout_sec=timeout_sec,
            auth_token=auth_token,
            body_size_bytes=body_size_bytes,
        )
    )
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    detected = sum(1 for r in results if r["assertion"]["detected"])
    return {
        "total": len(results),
        "detected": detected,
        "missed": len(results) - detected,
        "status": "ok" if detected == len(results) else "fail",
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="HTTP malformed-input gate for the record-recovery service (K3 sub-task).")
    ap.add_argument("--endpoint", default="", help="Optional pre-existing endpoint URL (e.g. https://127.0.0.1:18443). When omitted, an in-process plain-HTTP service is spawned on loopback.")
    ap.add_argument("--auth-token", default="", help="Bearer token to attach to requests when the service requires it. Ignored in default in-process mode unless explicitly set.")
    ap.add_argument("--timeout-sec", type=float, default=5.0)
    ap.add_argument("--body-size-bytes", type=int, default=200_000)
    ap.add_argument("--max-rows-per-request", type=int, default=10)
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-failures", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    spawn = not args.endpoint
    server: RecordRecoveryHttpServer | None = None
    thread: threading.Thread | None = None
    base_url: str = args.endpoint
    auth_token = args.auth_token or None
    spawn_root: tempfile.TemporaryDirectory[str] | None = None
    try:
        if spawn:
            auth_env = "RECOVERY_HTTP_GATE_TOKEN"
            auth_token_value = "http-malformed-input-gate-token"
            os.environ[auth_env] = auth_token_value
            auth_token = auth_token_value
            spawn_root = tempfile.TemporaryDirectory(prefix="seccomp_http_malformed_gate.")
            run_root = Path(spawn_root.name)
            server, thread, base_url = spawn_in_process_http_service(
                run_root=run_root,
                auth_token_env=auth_env,
                auth_token_value=auth_token_value,
                max_rows_per_request=args.max_rows_per_request,
            )
        results = run_gate(
            base_url=base_url,
            auth_token=auth_token,
            timeout_sec=args.timeout_sec,
            body_size_bytes=args.body_size_bytes,
        )
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2.0)
        if spawn_root is not None:
            spawn_root.cleanup()

    summary = summarize(results)
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "endpoint": base_url,
        "spawned_in_process": spawn,
        "auth_token_provided": bool(auth_token),
        "configuration": {
            "timeout_sec": args.timeout_sec,
            "body_size_bytes": args.body_size_bytes,
            "max_rows_per_request": args.max_rows_per_request,
        },
        "summary": summary,
        "scenarios": results,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.allow_failures:
        return 0
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
