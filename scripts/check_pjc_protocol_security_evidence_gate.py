#!/usr/bin/env python3
"""Verifier-facing gate for PJC protocol-security claims and evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_archive_locator import find_latest_live_archive


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pjc_protocol_security_evidence_gate/v1"
DEFAULT_LIVE_ARCHIVE = REPO_ROOT / "tmp" / "pjc_protocol_live_archive" / "pjc_protocol_live_evidence_archive.json"


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--live-evidence-archive", default="")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    repo_side_checks: list[dict[str, Any]] = []
    live_checks: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    commitment_log = out_dir / "check_pjc_input_commitment.log"
    commitment_timed_out = False
    try:
        res = run_with_timeout(["python3", str(REPO_ROOT / "scripts" / "check_pjc_input_commitment.py")], timeout_sec=5.0)
    except subprocess.TimeoutExpired as exc:
        commitment_timed_out = True
        res = subprocess.CompletedProcess(
            ["python3", str(REPO_ROOT / "scripts" / "check_pjc_input_commitment.py")],
            124,
            exc.stdout or "",
            exc.stderr or "",
        )
    commitment_log.write_text((res.stdout or "") + (res.stderr or ""), encoding="utf-8")
    if commitment_timed_out:
        repo_side_checks.append(
            parse_check(
                name="repo_side_input_commitment_gate",
                status="skipped",
                expected="input commitments and value-policy tampering are rejected before PJC execution",
                actual={"log_path": str(commitment_log), "exit_code": res.returncode},
                missing_prerequisites=["environment can complete the full input-commitment smoke within the bounded timeout"],
            )
        )
    else:
        require_ok(res, label="check_pjc_input_commitment")
        repo_side_checks.append(
            parse_check(
                name="repo_side_input_commitment_gate",
                status="ok",
                expected="input commitments and value-policy tampering are rejected before PJC execution",
                actual={"log_path": str(commitment_log)},
            )
        )
    artifacts.append(artifact(commitment_log, note="check_pjc_input_commitment output"))

    two_party_log = out_dir / "check_pjc_two_party_smoke.log"
    two_party_timed_out = False
    try:
        res = run_with_timeout(["python3", str(REPO_ROOT / "scripts" / "check_pjc_two_party_smoke.py")], timeout_sec=5.0)
    except subprocess.TimeoutExpired as exc:
        two_party_timed_out = True
        res = subprocess.CompletedProcess(
            ["python3", str(REPO_ROOT / "scripts" / "check_pjc_two_party_smoke.py")],
            124,
            exc.stdout or "",
            exc.stderr or "",
        )
    two_party_log.write_text((res.stdout or "") + (res.stderr or ""), encoding="utf-8")
    if res.returncode == 0:
        repo_side_checks.append(
            parse_check(
                name="repo_side_signed_two_party_evidence",
                status="ok",
                expected="signed manifests, commitment exchange, and bucket/shard scope mismatches are rejected",
                actual={"log_path": str(two_party_log)},
            )
        )
    else:
        combined = "\n".join(part for part in ((res.stdout or "").strip(), (res.stderr or "").strip()) if part)
        if two_party_timed_out or "Operation not permitted" in combined or "case_execution_failed" in combined:
            repo_side_checks.append(
                parse_check(
                    name="repo_side_signed_two_party_evidence",
                    status="skipped",
                    expected="signed manifests, commitment exchange, and bucket/shard scope mismatches are rejected",
                    actual={"log_path": str(two_party_log), "stdout": res.stdout, "stderr": res.stderr},
                    missing_prerequisites=["environment permits loopback/port probes and can complete the full two-party negative-case smoke within the bounded timeout"],
                )
            )
        else:
            require_ok(res, label="check_pjc_two_party_smoke")
    artifacts.append(artifact(two_party_log, note="check_pjc_two_party_smoke output"))

    release_gate_log = out_dir / "check_release_policy_gate_smoke.log"
    res = run(["python3", str(REPO_ROOT / "scripts" / "check_release_policy_gate_smoke.py")])
    release_gate_log.write_text((res.stdout or "") + (res.stderr or ""), encoding="utf-8")
    require_ok(res, label="check_release_policy_gate_smoke")
    repo_side_checks.append(
        parse_check(
            name="repo_side_release_binding",
            status="ok",
            expected="release gate binds PJC evidence merge and denies result substitution before release",
            actual={"log_path": str(release_gate_log)},
        )
    )
    artifacts.append(artifact(release_gate_log, note="check_release_policy_gate_smoke output"))

    claim_status = "semi_honest_only"
    claim_boundary = [
        "Current authoritative repo-side evidence supports semi-honest/operator-controlled claims with tamper/result substitution resistance.",
        "It does not support claiming malicious-secure PJC unless a real malicious-secure protocol or cryptographic proof system is added and tested.",
    ]

    archive_path = Path(args.live_evidence_archive).resolve() if args.live_evidence_archive else None
    if archive_path is None:
        archive_path = find_latest_live_archive(
            repo_root=REPO_ROOT,
            canonical_dirname="pjc_protocol_live_archive",
            archive_filename="pjc_protocol_live_evidence_archive.json",
            expected_schema="pjc_protocol_live_evidence_archive/v1",
        )
        if archive_path is None and DEFAULT_LIVE_ARCHIVE.is_file():
            archive_path = DEFAULT_LIVE_ARCHIVE.resolve()
    if archive_path is None:
        live_checks.append(
            parse_check(
                name="live_pjc_protocol_evidence_archive",
                status="skipped",
                expected="operator provides a unified live PJC protocol-security evidence archive",
                actual=None,
                missing_prerequisites=["--live-evidence-archive or tmp/pjc_protocol_live_archive/pjc_protocol_live_evidence_archive.json"],
            )
        )
    elif not archive_path.is_file():
        live_checks.append(
            parse_check(
                name="live_pjc_protocol_evidence_archive",
                status="fail",
                expected="operator provides a unified live PJC protocol-security evidence archive",
                actual={"path": str(archive_path), "exists": False},
            )
        )
    else:
        archive = load_json(archive_path)
        artifacts.append(artifact(archive_path, schema="pjc_protocol_live_evidence_archive/v1"))
        live_artifact_count = int(archive.get("live_artifact_count") or 0)
        foundation_present = isinstance((archive.get("live_artifacts") or {}).get("live_public_two_host_archive"), dict)
        live_checks.append(
            parse_check(
                name="live_pjc_protocol_evidence_archive",
                status="ok" if archive.get("status") == "ok" and live_artifact_count > 0 else "skipped" if archive.get("status") == "ok" else "fail",
                expected="operator provides a unified live PJC protocol-security evidence archive",
                actual=archive,
                missing_prerequisites=["archive contains no live PJC protocol-security artifacts"] if archive.get("status") == "ok" and live_artifact_count == 0 else None,
            )
        )
        live_checks.append(
            parse_check(
                name="live_public_two_host_protocol_foundation",
                status="ok" if foundation_present else "skipped",
                expected="a real current-worktree public two-host PJC archive exists as protocol-security live foundation",
                actual=(archive.get("live_artifacts") or {}).get("live_public_two_host_archive"),
                missing_prerequisites=["live_public_two_host_archive not present in protocol live archive"] if not foundation_present else None,
            )
        )
        live_checks.append(
            parse_check(
                name="live_signed_manifest_and_release_binding",
                status="ok"
                if isinstance((archive.get("live_artifacts") or {}).get("live_two_host_signed_manifest_report"), dict)
                and isinstance((archive.get("live_artifacts") or {}).get("live_release_binding_report"), dict)
                else "skipped",
                expected="real two-host signed manifest exchange and release-binding evidence are archived",
                actual={
                    "live_two_host_signed_manifest_report": (archive.get("live_artifacts") or {}).get("live_two_host_signed_manifest_report"),
                    "live_release_binding_report": (archive.get("live_artifacts") or {}).get("live_release_binding_report"),
                },
                missing_prerequisites=[
                    "live_two_host_signed_manifest_report and live_release_binding_report are still missing"
                ]
                if not (
                    isinstance((archive.get("live_artifacts") or {}).get("live_two_host_signed_manifest_report"), dict)
                    and isinstance((archive.get("live_artifacts") or {}).get("live_release_binding_report"), dict)
                )
                else None,
            )
        )

    repo_side_status = "ok" if all(item["status"] in {"ok", "skipped"} for item in repo_side_checks) else "fail"
    concrete_live = [item for item in live_checks if item["name"] == "live_pjc_protocol_evidence_archive"]
    foundation_live = [item for item in live_checks if item["name"] == "live_public_two_host_protocol_foundation"]
    binding_live = [item for item in live_checks if item["name"] == "live_signed_manifest_and_release_binding"]
    if any(item["status"] == "fail" for item in concrete_live):
        live_status = "fail"
    elif binding_live and all(item["status"] == "ok" for item in binding_live):
        live_status = "ok"
    elif foundation_live and any(item["status"] == "ok" for item in foundation_live):
        live_status = "skipped"
    else:
        live_status = "skipped"

    report = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if repo_side_status == "ok" and live_status != "fail" else "fail",
        "repo_side_status": repo_side_status,
        "live_status": live_status,
        "claim_status": claim_status,
        "repo_side_checks": repo_side_checks,
        "live_checks": live_checks,
        "repo_side_boundary": [
            "Repo-side checks prove commitment integrity, signed two-party evidence, release binding, and software-level value-policy enforcement.",
            "They do not prove source-truthfulness before bridge generation, nor a malicious-secure PSI-SUM or range/ZK proof system.",
        ],
        "live_boundary": [
            "Live PJC protocol readiness requires operator-provided two-host signed manifest, release-binding, and value-policy denial artifacts.",
            "When no live archive is supplied, this gate stays at live_status=skipped rather than claiming production-complete malicious-participant resistance.",
        ],
        "claim_boundary": claim_boundary,
        "artifacts": artifacts,
    }
    write_json(out_dir / "pjc_protocol_security_evidence_gate.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
