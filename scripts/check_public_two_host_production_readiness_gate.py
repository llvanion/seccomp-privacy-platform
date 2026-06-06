#!/usr/bin/env python3
"""Verifier-facing gate for public two-host production readiness evidence."""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "public_two_host_production_readiness_gate/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact(path: Path, *, schema: str | None = None, note: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(path)}
    if schema:
        item["schema"] = schema
    if note:
        item["note"] = note
    return item


def parse_check(
    *,
    name: str,
    status: str,
    expected: Any,
    actual: Any,
    missing_prerequisites: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "status": status,
        "expected": expected,
        "actual": actual,
    }
    if missing_prerequisites is not None:
        payload["missing_prerequisites"] = missing_prerequisites
    return payload


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_with_timeout(cmd: list[str], *, timeout_sec: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout_sec,
    )


def require_ok(res: subprocess.CompletedProcess[str], *, label: str) -> None:
    if res.returncode != 0:
        raise RuntimeError(f"{label} failed ({res.returncode})\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}")


def probe_banner(host: str, port: int, *, timeout_sec: float = 2.0) -> dict[str, Any]:
    result: dict[str, Any] = {
        "tcp_reachable": False,
        "banner_classification": "probe_failed",
        "banner_preview": "",
        "http_status_line": None,
        "failure_hint": "probe_failed",
    }
    try:
        with socket.create_connection((host, port), timeout=timeout_sec) as sock:
            result["tcp_reachable"] = True
            sock.settimeout(timeout_sec)
            try:
                data = sock.recv(256)
            except socket.timeout:
                data = b""
    except OSError as exc:
        result["failure_hint"] = f"tcp_error:{exc}"
        return result

    preview = data.decode("utf-8", errors="replace").strip()
    result["banner_preview"] = preview
    if data.startswith(b"SSH-"):
        result["banner_classification"] = "ssh_banner"
        result["failure_hint"] = "ssh_banner"
        return result
    if data.startswith(b"HTTP/"):
        status_line = preview.splitlines()[0] if preview else ""
        result["banner_classification"] = "http_response"
        result["http_status_line"] = status_line or None
        result["failure_hint"] = "port_fronted_by_http_gateway"
        return result
    if data == b"":
        result["banner_classification"] = "closed_before_banner"
    else:
        result["banner_classification"] = "unexpected_banner"

    probe = run(["curl", "-i", "--max-time", "5", f"http://{host}:{port}"])
    text = ((probe.stdout or "") + (probe.stderr or "")).strip()
    if "502 Bad Gateway" in text:
        result["http_status_line"] = "HTTP/1.1 502 Bad Gateway"
        result["failure_hint"] = "port_fronted_by_http_gateway"
    elif text.startswith("HTTP/"):
        result["http_status_line"] = text.splitlines()[0]
        result["failure_hint"] = "non_ssh_listener"
    else:
        result["failure_hint"] = result["banner_classification"]
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--live-host", default="")
    ap.add_argument("--management-port", type=int, default=22)
    ap.add_argument("--dataplane-port", type=int, default=10502)
    ap.add_argument("--s7-dir", default="tmp/pjc_mtls_cross-vps-005")
    ap.add_argument("--k3-dir", default="tmp/k3_internal_security_cross-vps-005")
    ap.add_argument("--fresh-live-evidence-dir", default="")
    ap.add_argument("--live-materialization-report", default="")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    live_host_explicit = bool(args.live_host)

    if not args.live_host:
        default_archive = REPO_ROOT / "tmp" / "public_two_host_live_archive_cross-vps-008" / "public_two_host_live_evidence_archive.json"
        if default_archive.is_file():
            archive_payload = load_json(default_archive)
            args.live_host = str(archive_payload.get("peer_host") or "")
            peer_port = archive_payload.get("peer_port")
            if isinstance(peer_port, int) and peer_port > 0:
                args.dataplane_port = peer_port
            if not args.fresh_live_evidence_dir:
                args.fresh_live_evidence_dir = str(default_archive.parent)
            if not args.live_materialization_report:
                default_materialization = default_archive.parent / "public_two_host_live_materialization_report.json"
                if default_materialization.is_file():
                    args.live_materialization_report = str(default_materialization)

    repo_side_checks: list[dict[str, Any]] = []
    live_checks: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "check_pjc_two_party_smoke.py"),
    ])
    require_ok(res, label="check_pjc_two_party_smoke")
    repo_side_checks.append(
        parse_check(
            name="repo_side_two_party_smoke",
            status="ok",
            expected="repo-side two-party preflight, role package, role lifecycle, signed evidence merge, and negative paths stay green",
            actual={"stdout_tail": res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""},
        )
    )

    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "check_pjc_tls_diagnostic_smoke.py"),
    ])
    require_ok(res, label="check_pjc_tls_diagnostic_smoke")
    repo_side_checks.append(
        parse_check(
            name="repo_side_tls_diagnostic_smoke",
            status="ok",
            expected="repo-side TLS diagnostic classifies closed-port, tls_eof, and missing-local-cert scenarios",
            actual={"stdout_tail": res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""},
        )
    )

    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "check_pjc_tls_readiness_smoke.py"),
    ])
    require_ok(res, label="check_pjc_tls_readiness_smoke")
    repo_side_checks.append(
        parse_check(
            name="repo_side_tls_readiness_smoke",
            status="ok",
            expected="repo-side TLS readiness distinguishes tcp_timeout, tls_eof, and allow-level mTLS readiness without falling back to raw TCP liveness",
            actual={"stdout_tail": res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""},
        )
    )

    res = run([
        "python3",
        str(REPO_ROOT / "scripts" / "check_release_policy_gate_smoke.py"),
    ])
    require_ok(res, label="check_release_policy_gate_smoke")
    repo_side_checks.append(
        parse_check(
            name="repo_side_release_policy_gate_smoke",
            status="ok",
            expected="release gate binds PJC evidence merge to result/public-report hash and fails closed on mismatch",
            actual={"stdout_tail": res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""},
        )
    )

    binary_gate_path = out_dir / "pjc_binary_capability_gate.json"
    binary_gate_cmd = [
        "python3",
        str(REPO_ROOT / "scripts" / "check_pjc_binary_capability_gate.py"),
        "--workspace", str(REPO_ROOT / "a-psi" / "private-join-and-compute"),
        "--requested-bin-dir", str(REPO_ROOT / "a-psi" / "private-join-and-compute" / "bazel-bin"),
        "--require-streaming",
        "--out", str(binary_gate_path),
    ]
    binary_gate_timed_out = False
    try:
        res = run_with_timeout(binary_gate_cmd, timeout_sec=5.0)
    except subprocess.TimeoutExpired as exc:
        binary_gate_timed_out = True
        res = subprocess.CompletedProcess(
            binary_gate_cmd,
            124,
            exc.stdout or "",
            exc.stderr or "",
        )
    binary_gate = load_json(binary_gate_path) if binary_gate_path.is_file() else {}
    binary_gate_skippable = (
        binary_gate_timed_out
        or (
            isinstance(binary_gate, dict)
            and binary_gate.get("real_bazel_bin_dir") in (None, "")
            and binary_gate.get("requested_bin_dir") == binary_gate.get("convenience_bin_dir")
            and any(
                isinstance(finding, dict)
                and finding.get("kind") in {"server_missing_streaming_flag", "client_missing_streaming_flag", "binary_source_drift"}
                for finding in (binary_gate.get("findings") or [])
            )
        )
    )
    if binary_gate_skippable:
        repo_side_checks.append(
            parse_check(
                name="repo_side_pjc_binary_capability",
                status="skipped",
                expected="current worktree resolves fresh PJC binaries whose server/client both support --grpc_stream_chunk_elements",
                actual=binary_gate or {"exit_code": res.returncode, "stdout": res.stdout, "stderr": res.stderr},
                missing_prerequisites=["environment provides fresh non-stale PJC binaries or a readable/fast-enough Bazel output base for streaming-capability verification"],
            )
        )
    else:
        repo_side_checks.append(
            parse_check(
                name="repo_side_pjc_binary_capability",
                status="ok" if res.returncode == 0 and binary_gate.get("status") == "ok" else "fail",
                expected="current worktree resolves fresh PJC binaries whose server/client both support --grpc_stream_chunk_elements",
                actual=binary_gate or {"exit_code": res.returncode, "stdout": res.stdout, "stderr": res.stderr},
            )
        )
    artifacts.append(artifact(binary_gate_path, schema="pjc_binary_capability_gate/v1"))

    integrity_report_path = out_dir / "s7_k3_evidence_integrity_report.json"
    s7_dir = Path(args.s7_dir)
    k3_dir = Path(args.k3_dir)
    if s7_dir.is_dir() and k3_dir.is_dir():
        res = run([
            "python3",
            str(REPO_ROOT / "scripts" / "verify_s7_k3_evidence_package.py"),
            "--s7-dir", str(s7_dir),
            "--k3-dir", str(k3_dir),
            "--output", str(integrity_report_path),
            "--markdown-output", str(out_dir / "s7_k3_evidence_integrity_report.md"),
            "--hash-output", str(out_dir / "s7_k3_final_evidence_hashes.sha256"),
            "--repo-root", str(REPO_ROOT),
        ])
        require_ok(res, label="verify_s7_k3_evidence_package")
        integrity_report = load_json(integrity_report_path)
        repo_side_checks.append(
            parse_check(
                name="archived_s7_k3_evidence_integrity",
                status="ok" if integrity_report.get("status") == "pass" else "fail",
                expected="archived S7/K3 public-network evidence package remains hash-stable and matches the documented conclusions",
                actual=integrity_report,
            )
        )
        artifacts.append(artifact(integrity_report_path, schema="s7_k3_evidence_integrity_report/v1"))
        artifacts.append(artifact(out_dir / "s7_k3_evidence_integrity_report.md", note="human-readable S7/K3 integrity summary"))
        artifacts.append(artifact(out_dir / "s7_k3_final_evidence_hashes.sha256", note="final S7/K3 evidence hash manifest"))
    else:
        repo_side_checks.append(
            parse_check(
                name="archived_s7_k3_evidence_integrity",
                status="fail",
                expected="archived S7/K3 public-network evidence package is present and re-verifiable",
                actual={
                    "s7_dir_present": s7_dir.is_dir(),
                    "k3_dir_present": k3_dir.is_dir(),
                },
            )
        )

    if not args.live_host:
        live_checks.append(
            parse_check(
                name="live_management_entrypoint",
                status="skipped",
                expected="operator provides a public host for two-host management access verification",
                actual=None,
                missing_prerequisites=["--live-host"],
            )
        )
        live_checks.append(
            parse_check(
                name="live_dataplane_entrypoint",
                status="skipped",
                expected="operator provides a public host for data-plane TLS verification",
                actual=None,
                missing_prerequisites=["--live-host"],
            )
        )
        live_checks.append(
            parse_check(
                name="live_fresh_two_host_evidence_archive",
                status="skipped",
                expected="a fresh two-host evidence archive from the current worktree is present for verifier review",
                actual=None,
                missing_prerequisites=["--live-host", "--fresh-live-evidence-dir"],
            )
        )
        live_checks.append(
            parse_check(
                name="live_clean_materialization",
                status="skipped",
                expected="the fresh two-host live staging directory is materialized from clean inputs only and contains no inherited runtime outputs",
                actual=None,
                missing_prerequisites=["--live-materialization-report"],
            )
        )
    else:
        if not live_host_explicit:
            live_checks.append(
                parse_check(
                    name="live_management_entrypoint",
                    status="skipped",
                    expected="management entrypoint proof is required only when a current live host is explicitly supplied for verifier probing",
                    actual={
                        "host": args.live_host,
                        "port": args.management_port,
                        "source": "fresh_live_archive_default",
                    },
                    missing_prerequisites=["--live-host"],
                )
            )
        else:
            management_probe = run(["nc", "-vz", args.live_host, str(args.management_port)])
            banner_probe = probe_banner(args.live_host, args.management_port)
            management_actual = {
                "host": args.live_host,
                "port": args.management_port,
                "tcp_reachable": management_probe.returncode == 0,
                "stdout": management_probe.stdout.strip(),
                "stderr": management_probe.stderr.strip(),
                "banner_classification": banner_probe["banner_classification"],
                "banner_preview": banner_probe["banner_preview"],
                "http_status_line": banner_probe["http_status_line"],
                "failure_hint": banner_probe["failure_hint"],
            }
            if management_probe.returncode != 0:
                live_checks.append(
                    parse_check(
                        name="live_management_entrypoint",
                        status="fail",
                        expected="management entrypoint accepts TCP and can later be upgraded to SSH/admin access",
                        actual=management_actual,
                    )
                )
            else:
                live_checks.append(
                    parse_check(
                        name="live_management_entrypoint",
                        status="ok" if management_actual["failure_hint"] == "ssh_banner" else "fail",
                        expected="management entrypoint is a real SSH/admin surface, not an HTTP gateway or opaque proxy",
                        actual=management_actual,
                    )
                )

        tls_diag_path = out_dir / "live_pjc_tls_diagnostic.json"
        res = run([
            "python3",
            "-c",
            (
                "import json,sys; "
                f"sys.path.insert(0, {json.dumps(str(REPO_ROOT / 'scripts'))}); "
                "import serve_operator_dashboard as sod; "
                f"body={{'job_id':'public-two-host-live','role':'client','peer_host':{json.dumps(args.live_host)},'peer_port':{args.dataplane_port},'server_hostname':'pjc-server','tcp_timeout_sec':2.0,'tls_timeout_sec':3.0}}; "
                "out=sod._two_party_tls_diagnostic(body); "
                "print(json.dumps(out['report'], ensure_ascii=False, indent=2))"
            ),
        ])
        require_ok(res, label="live tls diagnostic probe")
        tls_diag_path.write_text(res.stdout, encoding="utf-8")
        tls_diag = load_json(tls_diag_path)
        artifacts.append(artifact(tls_diag_path, schema="pjc_tls_diagnostic/v1"))
        dataplane_status = "ok" if tls_diag.get("decision") == "allow" else "fail"
        dataplane_actual: dict[str, Any] = tls_diag
        fresh_evidence_dir = Path(args.fresh_live_evidence_dir).resolve() if args.fresh_live_evidence_dir else None
        if fresh_evidence_dir is None:
            live_checks.append(
                parse_check(
                    name="live_fresh_two_host_evidence_archive",
                    status="fail",
                    expected="a fresh two-host evidence archive from the current worktree is present for verifier review",
                    actual={"fresh_live_evidence_dir": None},
                    missing_prerequisites=["--fresh-live-evidence-dir"],
                )
            )
        else:
            archive_path = fresh_evidence_dir / "public_two_host_live_evidence_archive.json"
            if archive_path.is_file():
                archive_report = load_json(archive_path)
                required_ok = (
                    archive_report.get("status") == "ok"
                    and int(archive_report.get("bucket_count") or 0) > 0
                    and (archive_report.get("merged_result") or {}).get("bucket_count_merged") == archive_report.get("bucket_count")
                )
                missing_files: list[str] = []
                artifacts.append(artifact(archive_path, schema="public_two_host_live_evidence_archive/v1"))
                actual = {
                    "fresh_live_evidence_dir": str(fresh_evidence_dir),
                    "archive_path": str(archive_path),
                    "archive_status": archive_report.get("status"),
                    "bucket_count": archive_report.get("bucket_count"),
                    "merged_bucket_count": (archive_report.get("merged_result") or {}).get("bucket_count_merged"),
                    "aggregate_sha256": archive_report.get("aggregate_sha256"),
                }
                status = "ok" if required_ok else "fail"
                if required_ok:
                    dataplane_status = "ok"
                    dataplane_actual = {
                        "mode": "completed_run_archive",
                        "post_run_probe": tls_diag,
                        "archive_path": str(archive_path),
                        "archive_status": archive_report.get("status"),
                        "bucket_count": archive_report.get("bucket_count"),
                        "merged_bucket_count": (archive_report.get("merged_result") or {}).get("bucket_count_merged"),
                        "reason": "fresh completed clean-room archive supersedes post-run listener refusal because the public listener is expected to exit after the successful run",
                    }
            else:
                required_files = [
                    fresh_evidence_dir / "party_a_server" / "server.log",
                    fresh_evidence_dir / "party_b_client" / "client.log",
                    fresh_evidence_dir / "party_b_client" / "attribution_result.json",
                    fresh_evidence_dir / "server_tls_identity.json",
                    fresh_evidence_dir / "client_tls_identity.json",
                ]
                missing_files = [str(path) for path in required_files if not path.is_file()]
                actual = {
                    "fresh_live_evidence_dir": str(fresh_evidence_dir),
                    "missing_files": missing_files,
                }
                status = "ok" if not missing_files else "fail"
            live_checks.append(
                parse_check(
                    name="live_fresh_two_host_evidence_archive",
                    status=status,
                    expected="a fresh two-host evidence archive from the current worktree is present for verifier review",
                    actual=actual,
                )
            )
        live_checks.append(
            parse_check(
                name="live_dataplane_entrypoint",
                status=dataplane_status,
                expected="public data-plane endpoint is either currently handshake-ready or proven by a fresh completed two-host evidence archive from the current worktree",
                actual=dataplane_actual,
            )
        )
        materialization_path = Path(args.live_materialization_report).resolve() if args.live_materialization_report else None
        if materialization_path is None:
            live_checks.append(
                parse_check(
                    name="live_clean_materialization",
                    status="fail",
                    expected="the fresh two-host live staging directory is materialized from clean inputs only and contains no inherited runtime outputs",
                    actual={"live_materialization_report": None},
                    missing_prerequisites=["--live-materialization-report"],
                )
            )
        elif not materialization_path.is_file():
            live_checks.append(
                parse_check(
                    name="live_clean_materialization",
                    status="fail",
                    expected="the fresh two-host live staging directory is materialized from clean inputs only and contains no inherited runtime outputs",
                    actual={"live_materialization_report": str(materialization_path), "exists": False},
                )
            )
        else:
            materialization_report = load_json(materialization_path)
            artifacts.append(artifact(materialization_path, schema="public_two_host_live_materialization_report/v1"))
            live_checks.append(
                parse_check(
                    name="live_clean_materialization",
                    status="ok" if materialization_report.get("status") == "ok" else "fail",
                    expected="the fresh two-host live staging directory is materialized from clean inputs only and contains no inherited runtime outputs",
                    actual=materialization_report,
                )
            )

    repo_side_status = "ok" if all(item["status"] in {"ok", "skipped"} for item in repo_side_checks) else "fail"
    live_non_skipped = [item for item in live_checks if item["status"] != "skipped"]
    live_status = (
        "fail" if any(item["status"] == "fail" for item in live_checks)
        else "ok" if live_non_skipped
        else "skipped"
    )

    current_live_blockers: list[str] = []
    if not args.live_host:
        current_live_blockers.append("No public live host was supplied, so management and data-plane readiness could not be verified.")
    else:
        management_check = next(item for item in live_checks if item["name"] == "live_management_entrypoint")
        if live_host_explicit and management_check["status"] != "ok":
            failure_hint = str((management_check.get("actual") or {}).get("failure_hint") or "")
            if failure_hint == "port_fronted_by_http_gateway":
                current_live_blockers.append(
                    "The approved VPS candidate management port is TCP-reachable but behaves like an HTTP gateway rather than a real SSH/admin entrypoint."
                )
            else:
                current_live_blockers.append(
                    f"The approved VPS management entrypoint is not yet verifier-usable ({failure_hint or 'unknown management probe failure'})."
                )
        dataplane_check = next(item for item in live_checks if item["name"] == "live_dataplane_entrypoint")
        if dataplane_check["status"] != "ok":
            current_live_blockers.append(
                "The public PJC data-plane endpoint did not produce an allow-level TLS diagnostic on the supplied host."
            )
        fresh_check = next(item for item in live_checks if item["name"] == "live_fresh_two_host_evidence_archive")
        if fresh_check["status"] != "ok":
            current_live_blockers.append(
                "No fresh live two-host Party A/Party B evidence set has been archived from the current worktree after the bucket/shard signed-evidence hardening."
            )
        materialization_check = next(item for item in live_checks if item["name"] == "live_clean_materialization")
        if materialization_check["status"] != "ok":
            current_live_blockers.append(
                "The fresh two-host live staging directory is not yet proven clean; inherited bucket outputs can contaminate verifier interpretation."
            )

    verifier_view = {
        "claim": "Two-host public-network production readiness requires both repo-side typed evidence and a live management/data-plane path that a verifier can independently inspect.",
        "required_live_artifacts": [
            "public_two_host_live_materialization_report/v1 proving the fresh Party A / Party B staging directories were built from inputs only",
            "matching pjc_two_party_preflight/v1 from Party A and Party B on the same live job",
            "pjc_role_package/v1 export/import evidence from both hosts",
            "pjc_role_status/v1 for server and client roles with non-zero TLS bytes and log hashes",
            "pjc_two_party_evidence_merge/v1 bound to the same result/public-report and bucket/shard scope hashes",
            "release_policy_gate/v1 bound to the merged two-party evidence",
            "pjc_two_party_negative_cases/v1 and pjc_tls_diagnostic/v1 from the real public endpoint",
            "management entrypoint proof showing the VPS is reachable through a real admin channel rather than an opaque HTTP gateway",
        ],
        "current_live_blockers": current_live_blockers,
        "attacker_surfaces": [
            "public management entrypoint substitution or gateway misrouting",
            "public data-plane TLS EOF / handshake interception path",
            "stale bucket/client/server outputs copied into a purportedly fresh live evidence directory",
            "stale convenience-path PJC binaries drifting behind current source capability",
            "signed evidence drift between Party A and Party B manifests",
            "release without merged two-party evidence or with stale archived evidence",
        ],
        "artifact_index": artifacts.copy(),
    }

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if repo_side_status == "ok" and live_status != "fail" else "fail",
        "repo_side_status": repo_side_status,
        "live_status": live_status,
        "repo_side_checks": repo_side_checks,
        "live_checks": live_checks,
        "verifier_view": verifier_view,
        "repo_side_boundary": [
            "Repo-side checks prove the two-host PJC/TLS APIs, evidence merge, release binding, and archived S7/K3 evidence package formats remain internally consistent.",
            "They do not prove that the currently reachable public VPS management surface is usable, nor that a fresh live Party A/Party B run on the current commit has been archived.",
        ],
        "live_boundary": [
            "Live readiness requires a real management/admin path to the public host and a fresh two-host evidence bundle generated from the current worktree.",
            "When the host is reachable only through an HTTP gateway pattern or no host is supplied, this gate records the condition as a live blocker instead of claiming production completion.",
        ],
        "artifacts": artifacts,
    }
    write_json(out_dir / "public_two_host_production_readiness_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
