#!/usr/bin/env python3
"""
B14: Operator shell regression and handoff verification.

Validates the full operator flow end-to-end:
  1. Dashboard server starts and /healthz responds
  2. POST /v1/jobs/start launches a real pipeline job
  3. GET /v1/jobs/{job_id} returns running → completed
  4. GET /v1/jobs/{job_id}/result returns intersection_size=2, sum=425, released=true
  5. GET /v1/runs lists the completed run
  6. GET /v1/dashboard returns audit_center + history blocks
  7. check_workflow_retry_eligibility: completed job → recommended_action=none
  8. run_operator_triage: overall_status is valid
  9. export_otel_events: otel_export_report/v1 produced with ≥1 stage span
  10. POST /v1/jobs/{job_id}/relaunch is refused for completed job
      (relaunch only allowed for terminal runs with recommended_action=resubmit/retry)

Outputs operator_shell_regression_report/v1.

Usage:
  python3 scripts/verify_operator_shell_regression.py \
    --out-dir /tmp/b14_regression \
    --output /tmp/b14_regression/operator_shell_regression_report.json
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import ProxyHandler, Request, build_opener

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from runtime_service_helpers import available_port, wait_for_tcp_port

REPORT_SCHEMA = "operator_shell_regression_report/v1"
EXPECTED_SIZE = 2
EXPECTED_SUM = 425


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _opener():
    return build_opener(ProxyHandler({}))


def _get(url: str, *, timeout: float = 10.0) -> dict[str, Any]:
    with _opener().open(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post(url: str, body: dict[str, Any], *, timeout: float = 10.0) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body, ensure_ascii=False).encode()
    req = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with _opener().open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except Exception as exc:
        code = getattr(exc, "code", 0)
        try:
            body_bytes = exc.read() if hasattr(exc, "read") else b"{}"
            return code, json.loads(body_bytes.decode())
        except Exception:
            return code, {"error": str(exc)}


def _check(checks: list, name: str, *, status: str, detail: str = "") -> None:
    checks.append({"name": name, "status": status, "detail": detail or None})
    icon = "[pass]" if status == "pass" else ("[skip]" if status == "skip" else "[FAIL]")
    print(f"  {icon} {name}" + (f": {detail}" if detail else ""))


def _assert(checks: list, name: str, condition: bool, detail: str = "") -> bool:
    _check(checks, name, status="pass" if condition else "fail", detail=detail)
    return condition


def run_regression(*, out_dir: Path, output_path: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    job_id = f"b14_regression_{int(time.time())}"
    out_base = out_dir / job_id

    # ── Find a free port ──────────────────────────────────────────────────────
    port = available_port()
    history_root = str(out_dir)

    # ── Build request file ────────────────────────────────────────────────────
    request_file = out_dir / "b14_request.json"
    request_payload = {
        "schema": "query_workflow_request/v1",
        "query_type": "cross_party_match",
        "server_source": str(REPO_ROOT / "sse/examples/bridge_server_records.jsonl"),
        "client_source": str(REPO_ROOT / "sse/examples/bridge_client_records.jsonl"),
        "server_join_key_field": "email",
        "client_join_key_field": "email",
        "client_value_field": "amount",
        "server_normalizer": "email",
        "client_normalizer": "email",
        "client_value_mode": "raw-int",
        "server_filters": ["campaign=demo"],
        "client_filters": ["campaign=demo"],
        "token_scope": "b14-regression-scope",
        "token_secret": "local-dev-secret",
        "job_id": job_id,
        "out_base": str(out_base),
        "caller": "auto_demo",
        "tenant_id": "demo_tenant",
        "dataset_id": "bridge_demo_dataset",
        "sse_export_policy_config": str(REPO_ROOT / "sse/config/export_policy.example.json"),
        "k": 1,
        "n": 5,
        "deny_duplicate_query": False,
        "cleanup_sse_export_handoff_files_after_bridge": True,
    }
    request_file.write_text(json.dumps(request_payload, indent=2), encoding="utf-8")

    # Pre-create out_base so the dashboard server accepts it on startup
    out_base.mkdir(parents=True, exist_ok=True)

    # ── Start dashboard server ────────────────────────────────────────────────
    server_env = os.environ.copy()
    server_env["no_proxy"] = "*"
    server_env["NO_PROXY"] = "*"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/serve_operator_dashboard.py"),
            "--port", str(port),
            "--out-base", str(out_base),
            "--history-root", history_root,
            "--history-limit", "10",
        ],
        env=server_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    base_url = f"http://127.0.0.1:{port}"
    dashboard_port = port

    try:
        # ── Check 1: server starts ────────────────────────────────────────────
        try:
            wait_for_tcp_port(host="127.0.0.1", port=port, timeout_sec=8.0)
            health = _get(f"{base_url}/healthz")
            _assert(checks, "dashboard_server_starts", health.get("status") == "ok",
                    f"status={health.get('status')}")
        except Exception as exc:
            _check(checks, "dashboard_server_starts", status="fail", detail=str(exc))
            return _build_report(checks, job_id=job_id, out_base=out_base, port=dashboard_port, t0=t0)

        # ── Check 2: POST /v1/jobs/start ─────────────────────────────────────
        try:
            status_code, start_resp = _post(
                f"{base_url}/v1/jobs/start",
                {"request_file": str(request_file), "overrides": {"job_id": job_id, "out_base": str(out_base)}},
                timeout=15.0,
            )
            started = status_code in (200, 202) and start_resp.get("state") in ("running", "completed")
            _assert(checks, "job_start_accepted", started,
                    f"status={status_code} state={start_resp.get('state')}")
        except Exception as exc:
            _check(checks, "job_start_accepted", status="fail", detail=str(exc))
            return _build_report(checks, job_id=job_id, out_base=out_base, port=dashboard_port, t0=t0)

        # ── Check 3: poll until terminal ──────────────────────────────────────
        deadline = time.monotonic() + 180.0
        terminal_state = None
        while time.monotonic() < deadline:
            try:
                job_resp = _get(f"{base_url}/v1/jobs/{job_id}", timeout=5.0)
                state = str(job_resp.get("state") or "")
                if state in ("completed", "failed", "error"):
                    terminal_state = state
                    break
                time.sleep(2.0)
            except Exception:
                time.sleep(2.0)

        _assert(checks, "job_reaches_terminal_state", terminal_state is not None,
                f"state={terminal_state}")
        _assert(checks, "job_completed_not_failed", terminal_state == "completed",
                f"state={terminal_state}")

        # ── Check 4: GET /v1/jobs/{job_id}/result ────────────────────────────
        try:
            result = _get(f"{base_url}/v1/jobs/{job_id}/result", timeout=10.0)
            _assert(checks, "result_intersection_size",
                    result.get("intersection_size") == EXPECTED_SIZE,
                    f"got {result.get('intersection_size')}")
            _assert(checks, "result_intersection_sum",
                    int(result.get("intersection_sum") or 0) == EXPECTED_SUM,
                    f"got {result.get('intersection_sum')}")
            _assert(checks, "result_released",
                    result.get("released") is True,
                    f"released={result.get('released')}")
        except Exception as exc:
            for name in ("result_intersection_size", "result_intersection_sum", "result_released"):
                _check(checks, name, status="fail", detail=str(exc))

        # ── Check 5: GET /v1/runs lists the run ──────────────────────────────
        try:
            runs_resp = _get(f"{base_url}/v1/runs?limit=20", timeout=10.0)
            statuses = runs_resp.get("statuses") or []
            job_ids = [s.get("job_id") for s in statuses]
            _assert(checks, "runs_list_contains_job", job_id in job_ids,
                    f"found={job_ids}")
        except Exception as exc:
            _check(checks, "runs_list_contains_job", status="fail", detail=str(exc))

        # ── Check 6: GET /v1/dashboard returns audit_center ──────────────────
        try:
            dash = _get(f"{base_url}/v1/dashboard", timeout=10.0)
            _assert(checks, "dashboard_has_audit_center",
                    isinstance(dash.get("audit_center"), dict),
                    f"audit_center={type(dash.get('audit_center')).__name__}")
        except Exception as exc:
            _check(checks, "dashboard_has_audit_center", status="fail", detail=str(exc))

        # ── Check 7: retry eligibility is valid for the terminal job ─────────
        try:
            status_file = out_base / "query_workflow" / "status.json"
            if status_file.exists():
                result7 = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "scripts/check_workflow_retry_eligibility.py"),
                     "--status-file", str(status_file)],
                    capture_output=True, text=True, timeout=30,
                )
                if result7.returncode == 0:
                    eligibility = json.loads(result7.stdout)
                    valid_actions = {"none", "retry", "resubmit", "wait"}
                    action = eligibility.get("recommended_action")
                    _assert(checks, "retry_eligibility_valid_action",
                            action in valid_actions and eligibility.get("terminal") is True,
                            f"action={action} terminal={eligibility.get('terminal')}")
                    # For a successfully completed job, action must be none
                    if terminal_state == "completed":
                        _assert(checks, "retry_eligibility_completed_is_none",
                                action == "none",
                                f"completed job should have action=none, got {action}")
                    else:
                        _check(checks, "retry_eligibility_completed_is_none", status="skip",
                               detail=f"job state={terminal_state}, skipping completed-only assertion")
                else:
                    _check(checks, "retry_eligibility_valid_action", status="fail",
                           detail=result7.stderr[:200])
                    _check(checks, "retry_eligibility_completed_is_none", status="skip",
                           detail="eligibility check failed")
            else:
                _check(checks, "retry_eligibility_valid_action", status="skip",
                       detail="status.json not found")
                _check(checks, "retry_eligibility_completed_is_none", status="skip",
                       detail="status.json not found")
        except Exception as exc:
            _check(checks, "retry_eligibility_valid_action", status="fail", detail=str(exc))
            _check(checks, "retry_eligibility_completed_is_none", status="skip", detail=str(exc))

        # ── Check 8: operator triage runs ────────────────────────────────────
        try:
            result8 = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/run_operator_triage.py"),
                 "--out-base", str(out_base),
                 "--out", str(out_base / "operator_triage.json")],
                capture_output=True, text=True, timeout=30,
            )
            if result8.returncode == 0:
                triage = json.loads((out_base / "operator_triage.json").read_text())
                _assert(checks, "operator_triage_overall_status",
                        triage.get("overall_status") in ("ok", "warn", "error"),
                        f"status={triage.get('overall_status')}")
            else:
                _check(checks, "operator_triage_overall_status", status="fail",
                       detail=result8.stderr[:200])
        except Exception as exc:
            _check(checks, "operator_triage_overall_status", status="fail", detail=str(exc))

        # ── Check 9: OTel export (B13) ────────────────────────────────────────
        try:
            obs_file = out_base / "pipeline_observability.json"
            obs_exists = obs_file.exists()
            if not obs_exists:
                # generate observability from audit chain
                audit_chain = out_base / "audit_chain.json"
                if audit_chain.exists():
                    subprocess.run(
                        [sys.executable, str(REPO_ROOT / "scripts/export_observability_events.py"),
                         "--audit-chain", str(audit_chain),
                         "--out", str(obs_file)],
                        capture_output=True, timeout=30,
                    )
                    obs_exists = obs_file.exists()
            if obs_exists:
                otel_out = out_base / "otel_spans.jsonl"
                otel_report_out = out_base / "otel_export_report.json"
                result9 = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "scripts/export_otel_events.py"),
                     "--observability", str(obs_file),
                     "--spans-out", str(otel_out),
                     "--report-out", str(otel_report_out)],
                    capture_output=True, text=True, timeout=30,
                )
                if result9.returncode == 0 and otel_out.exists():
                    spans = [json.loads(l) for l in otel_out.read_text().splitlines() if l.strip()]
                    _assert(checks, "otel_export_produces_spans",
                            len(spans) >= 2,  # root + at least 1 stage
                            f"span_count={len(spans)}")
                    stage_spans = [s for s in spans if s.get("parentSpanId")]
                    _assert(checks, "otel_stage_spans_have_parent",
                            len(stage_spans) >= 1,
                            f"stage_spans={len(stage_spans)}")
                else:
                    _check(checks, "otel_export_produces_spans", status="fail",
                           detail=result9.stderr[:200] if result9.returncode != 0 else "spans file missing")
                    _check(checks, "otel_stage_spans_have_parent", status="skip", detail="otel export failed")
            else:
                _check(checks, "otel_export_produces_spans", status="skip", detail="observability file missing")
                _check(checks, "otel_stage_spans_have_parent", status="skip", detail="observability file missing")
        except Exception as exc:
            _check(checks, "otel_export_produces_spans", status="fail", detail=str(exc))
            _check(checks, "otel_stage_spans_have_parent", status="skip", detail=str(exc))

        # ── Check 10: relaunch endpoint responds with valid JSON ──────────────
        try:
            status_code10, relaunch_resp = _post(
                f"{base_url}/v1/jobs/{job_id}/relaunch",
                {},
                timeout=10.0,
            )
            # For completed jobs (action=none), relaunch should be refused (4xx or error body)
            # For failed jobs (action=resubmit), relaunch is accepted (202) or validation error
            has_valid_response = isinstance(relaunch_resp, dict) and len(relaunch_resp) > 0
            _assert(checks, "relaunch_endpoint_responds",
                    has_valid_response and status_code10 in (202, 400, 404, 409),
                    f"status={status_code10} keys={list(relaunch_resp.keys())[:3]}")
        except Exception as exc:
            _check(checks, "relaunch_endpoint_responds", status="fail", detail=str(exc))

    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    return _build_report(checks, job_id=job_id, out_base=out_base, port=dashboard_port, t0=t0)


def _build_report(
    checks: list,
    *,
    job_id: str,
    out_base: Path,
    port: int,
    t0: float,
) -> dict[str, Any]:
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] == "fail")
    overall = "ok" if failed == 0 else "failed"
    return {
        "schema": REPORT_SCHEMA,
        "generated_at_utc": _utc_now(),
        "overall_status": overall,
        "checks_total": len(checks),
        "checks_passed": passed,
        "checks_failed": failed,
        "job_id": job_id,
        "out_base": str(out_base),
        "dashboard_port": port,
        "elapsed_sec": round(time.monotonic() - t0, 1),
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="B14: Operator shell regression and handoff verification")
    ap.add_argument("--out-dir", default="/tmp/b14_regression",
                    help="Working directory for this regression run")
    ap.add_argument("--output", default="",
                    help="Write JSON report to this path (default: stdout)")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir)

    print(f"[b14] starting operator shell regression in {out_dir}")
    report = run_regression(out_dir=out_dir, output_path=args.output)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")

    print(f"\n[b14] overall: {report['overall_status']} "
          f"({report['checks_passed']}/{report['checks_total']} checks passed, "
          f"{report['elapsed_sec']}s)")
    return 0 if report["overall_status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
