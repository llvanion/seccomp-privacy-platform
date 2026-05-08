#!/usr/bin/env python3
"""mTLS connection overhead benchmark for the record-recovery HTTP boundary (G6).

Spawns the record-recovery HTTP service in-process twice — once over plaintext
HTTP and once over mTLS using mock-issued certificates — and measures /health
round-trip latency over both. Each transport is exercised in two connection
modes:

- ``fresh_connection``: a new TLS handshake / TCP connection per request (worst
  case, mimics short-lived clients).
- ``persistent_connection``: one underlying connection reused for all requests
  (HTTP keep-alive baseline).

The report (``recovery_mtls_benchmark/v1``) records p50/p95/max latency for
each (transport, connection_mode) pair, the mTLS overhead deltas vs plaintext,
and a keep-alive improvement metric. The benchmark only exercises the
unauthenticated /health endpoint so it does not need a real record store, an
authz policy, or a bearer token; it is a pure connection-overhead measurement.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import ssl
import statistics
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    _build_server_ssl_context,
)
from services.record_recovery.runtime import build_service_state  # noqa: E402

from issue_mtls_certs import build_report as issue_mtls_cert_report  # noqa: E402

SCHEMA_ID = "recovery_mtls_benchmark/v1"
HEALTH_BODY = b'{"op":"health"}'


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    weight = pos - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(values: list[float]) -> dict[str, float | None]:
    return {
        "min": round(min(values), 3) if values else None,
        "mean": round(statistics.fmean(values), 3) if values else None,
        "p50": round(percentile(values, 0.50), 3) if values else None,
        "p95": round(percentile(values, 0.95), 3) if values else None,
        "max": round(max(values), 3) if values else None,
    }


def issue_mock_mtls_certs(out_dir: Path) -> dict[str, Any]:
    report = issue_mtls_cert_report(
        {
            "schema": "vault_pki_config/v1",
            "common_name": "127.0.0.1",
            "ip_sans": ["127.0.0.1"],
            "dns_sans": ["localhost"],
            "ttl_hours": 24,
            "issue_client_cert": True,
            "mock_mode": True,
        },
        out_dir=str(out_dir),
    )
    if not report.get("ok"):
        raise RuntimeError(f"mock mTLS cert issue failed: {report.get('error')}")
    issued = report.get("issued_files") or {}
    return {
        "server_cert": str(issued["server_cert"]),
        "server_key": str(issued["server_key"]),
        "ca_cert": str(issued["ca_cert"]),
        "client_cert": str(issued["client_cert"]),
        "client_key": str(issued["client_key"]),
    }


def spawn_http_service(
    *,
    run_root: Path,
    transport_label: str,
    tls_context: ssl.SSLContext | None,
) -> tuple[RecordRecoveryHttpServer, threading.Thread, int]:
    port = available_port()
    audit_log = run_root / f"{transport_label}_service_audit.jsonl"
    output_root = run_root / f"{transport_label}_outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    record_store_root = run_root / f"{transport_label}_store"
    record_store_root.mkdir(parents=True, exist_ok=True)
    state = build_service_state(
        service_id=f"recovery-mtls-bench-{transport_label}",
        tenant_id="recovery-mtls-bench-tenant",
        dataset_id="recovery-mtls-bench-dataset",
        auth_token_env="",
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
        max_rows_per_request=0,
    )
    server = RecordRecoveryHttpServer(
        ("127.0.0.1", port),
        RecordRecoveryHttpHandler,
        service_state=state,
        rate_limit_per_caller=0.0,
        rate_limit_burst=0,
    )
    if tls_context is not None:
        server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, port


def make_client_ssl_context(*, ca_cert: str, client_cert: str, client_key: str) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=ca_cert)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(certfile=client_cert, keyfile=client_key)
    return ctx


def _post_health_fresh(host: str, port: int, *, scheme: str, ssl_context: ssl.SSLContext | None, timeout: float) -> tuple[int, float]:
    started = time.perf_counter()
    if scheme == "https":
        conn = http.client.HTTPSConnection(host, port, context=ssl_context, timeout=timeout)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("POST", "/health", body=HEALTH_BODY, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        status = resp.status
        resp.read()
    finally:
        conn.close()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return status, elapsed_ms


def _post_health_persistent(conn: http.client.HTTPConnection | http.client.HTTPSConnection) -> tuple[int, float]:
    started = time.perf_counter()
    conn.request("POST", "/health", body=HEALTH_BODY, headers={"Content-Type": "application/json", "Connection": "keep-alive"})
    resp = conn.getresponse()
    status = resp.status
    resp.read()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return status, elapsed_ms


def measure_fresh(host: str, port: int, *, scheme: str, ssl_context: ssl.SSLContext | None, iterations: int, timeout: float) -> list[dict[str, Any]]:
    results = []
    for index in range(iterations):
        try:
            status, elapsed = _post_health_fresh(host, port, scheme=scheme, ssl_context=ssl_context, timeout=timeout)
            results.append({"iteration": index, "status_code": status, "duration_ms": round(elapsed, 3), "transport_error": None})
        except Exception as exc:
            results.append({"iteration": index, "status_code": 0, "duration_ms": None, "transport_error": f"{type(exc).__name__}: {exc}"})
    return results


def measure_persistent(host: str, port: int, *, scheme: str, ssl_context: ssl.SSLContext | None, iterations: int, timeout: float) -> list[dict[str, Any]]:
    if scheme == "https":
        conn: http.client.HTTPConnection | http.client.HTTPSConnection = http.client.HTTPSConnection(host, port, context=ssl_context, timeout=timeout)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    results = []
    try:
        for index in range(iterations):
            try:
                status, elapsed = _post_health_persistent(conn)
                results.append({"iteration": index, "status_code": status, "duration_ms": round(elapsed, 3), "transport_error": None})
            except Exception as exc:
                results.append({"iteration": index, "status_code": 0, "duration_ms": None, "transport_error": f"{type(exc).__name__}: {exc}"})
                # Recreate the connection on transport failure
                try:
                    conn.close()
                except Exception:
                    pass
                if scheme == "https":
                    conn = http.client.HTTPSConnection(host, port, context=ssl_context, timeout=timeout)
                else:
                    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return results


def successful_durations(results: list[dict[str, Any]]) -> list[float]:
    return [float(r["duration_ms"]) for r in results if r.get("status_code") == 200 and isinstance(r.get("duration_ms"), (int, float))]


def overhead(plain_p95: float | None, mtls_p95: float | None) -> float | None:
    if plain_p95 is None or mtls_p95 is None:
        return None
    return round(mtls_p95 - plain_p95, 3)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Benchmark mTLS connection overhead vs plaintext HTTP for the record-recovery /health endpoint.")
    ap.add_argument("--iterations", type=int, default=20)
    ap.add_argument("--timeout-sec", type=float, default=5.0)
    ap.add_argument("--mtls-overhead-warn-ms", type=float, default=50.0)
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-failures", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.iterations <= 0:
        raise SystemExit("[ERROR] --iterations must be positive")
    if args.timeout_sec <= 0:
        raise SystemExit("[ERROR] --timeout-sec must be positive")

    started_run = utc_now_iso()
    plain_server: RecordRecoveryHttpServer | None = None
    plain_thread: threading.Thread | None = None
    mtls_server: RecordRecoveryHttpServer | None = None
    mtls_thread: threading.Thread | None = None
    with tempfile.TemporaryDirectory(prefix="seccomp_mtls_overhead.") as tmp_dir:
        run_root = Path(tmp_dir)
        cert_dir = run_root / "mtls_certs"
        cert_dir.mkdir(parents=True, exist_ok=True)
        certs = issue_mock_mtls_certs(cert_dir)
        try:
            plain_server, plain_thread, plain_port = spawn_http_service(run_root=run_root, transport_label="plain", tls_context=None)
            tls_ctx = _build_server_ssl_context(
                cert_file=certs["server_cert"],
                key_file=certs["server_key"],
                ca_cert=certs["ca_cert"],
                require_client_cert=True,
            )
            mtls_server, mtls_thread, mtls_port = spawn_http_service(run_root=run_root, transport_label="mtls", tls_context=tls_ctx)
            client_ctx = make_client_ssl_context(
                ca_cert=certs["ca_cert"],
                client_cert=certs["client_cert"],
                client_key=certs["client_key"],
            )
            # Warmup (single fresh request each transport) so JIT / DNS / cert loading does not skew the measurement
            try:
                _post_health_fresh("127.0.0.1", plain_port, scheme="http", ssl_context=None, timeout=args.timeout_sec)
            except Exception:
                pass
            try:
                _post_health_fresh("127.0.0.1", mtls_port, scheme="https", ssl_context=client_ctx, timeout=args.timeout_sec)
            except Exception:
                pass
            plain_fresh = measure_fresh("127.0.0.1", plain_port, scheme="http", ssl_context=None, iterations=args.iterations, timeout=args.timeout_sec)
            plain_persistent = measure_persistent("127.0.0.1", plain_port, scheme="http", ssl_context=None, iterations=args.iterations, timeout=args.timeout_sec)
            mtls_fresh = measure_fresh("127.0.0.1", mtls_port, scheme="https", ssl_context=client_ctx, iterations=args.iterations, timeout=args.timeout_sec)
            mtls_persistent = measure_persistent("127.0.0.1", mtls_port, scheme="https", ssl_context=client_ctx, iterations=args.iterations, timeout=args.timeout_sec)
        finally:
            for srv in (plain_server, mtls_server):
                if srv is not None:
                    srv.shutdown()
                    srv.server_close()
            for th in (plain_thread, mtls_thread):
                if th is not None:
                    th.join(timeout=2.0)

    plain_fresh_durations = successful_durations(plain_fresh)
    plain_persistent_durations = successful_durations(plain_persistent)
    mtls_fresh_durations = successful_durations(mtls_fresh)
    mtls_persistent_durations = successful_durations(mtls_persistent)

    plain_fresh_summary = summarize(plain_fresh_durations)
    plain_persistent_summary = summarize(plain_persistent_durations)
    mtls_fresh_summary = summarize(mtls_fresh_durations)
    mtls_persistent_summary = summarize(mtls_persistent_durations)

    fresh_overhead_p95 = overhead(plain_fresh_summary["p95"], mtls_fresh_summary["p95"])
    persistent_overhead_p95 = overhead(plain_persistent_summary["p95"], mtls_persistent_summary["p95"])
    keep_alive_savings_mtls_p95 = (
        round(mtls_fresh_summary["p95"] - mtls_persistent_summary["p95"], 3)
        if mtls_fresh_summary["p95"] is not None and mtls_persistent_summary["p95"] is not None
        else None
    )

    overhead_ok = (
        fresh_overhead_p95 is not None
        and fresh_overhead_p95 < args.mtls_overhead_warn_ms
    )
    keep_alive_recommended = bool(
        fresh_overhead_p95 is not None and fresh_overhead_p95 >= args.mtls_overhead_warn_ms
    )
    keep_alive_helps = bool(
        keep_alive_savings_mtls_p95 is not None and keep_alive_savings_mtls_p95 > 0
    )

    successes = (
        len(plain_fresh_durations)
        + len(plain_persistent_durations)
        + len(mtls_fresh_durations)
        + len(mtls_persistent_durations)
    )
    total = args.iterations * 4
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": started_run,
        "configuration": {
            "iterations": args.iterations,
            "timeout_sec": args.timeout_sec,
            "mtls_overhead_warn_ms": args.mtls_overhead_warn_ms,
            "endpoint_path": "/health",
        },
        "summary": {
            "status": "ok" if successes == total else "fail",
            "total_requests": total,
            "successful_requests": successes,
            "fresh_connection_mtls_overhead_p95_ms": fresh_overhead_p95,
            "persistent_connection_mtls_overhead_p95_ms": persistent_overhead_p95,
            "keep_alive_savings_mtls_p95_ms": keep_alive_savings_mtls_p95,
            "fresh_overhead_under_warn_threshold": overhead_ok,
            "keep_alive_recommended": keep_alive_recommended,
            "keep_alive_helps": keep_alive_helps,
        },
        "transports": [
            {
                "transport": "plain_http",
                "connection_mode": "fresh_connection",
                "duration_ms": plain_fresh_summary,
                "results": plain_fresh,
            },
            {
                "transport": "plain_http",
                "connection_mode": "persistent_connection",
                "duration_ms": plain_persistent_summary,
                "results": plain_persistent,
            },
            {
                "transport": "mtls",
                "connection_mode": "fresh_connection",
                "duration_ms": mtls_fresh_summary,
                "results": mtls_fresh,
            },
            {
                "transport": "mtls",
                "connection_mode": "persistent_connection",
                "duration_ms": mtls_persistent_summary,
                "results": mtls_persistent,
            },
        ],
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.allow_failures:
        return 0
    return 0 if report["summary"]["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
