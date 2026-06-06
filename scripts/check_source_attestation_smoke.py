#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from validate_json_contract import load_json as load_schema_json, validate_value


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_source_attestation.py"
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_source_attestation.py"
SCHEMA = "source_truthfulness_smoke/v1"
SOURCE_REPORT_SCHEMA = load_schema_json(str(REPO_ROOT / "schemas" / "source_truthfulness_report.schema.json"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
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


def write_key(path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def fixture_inputs(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    server_source = root / "server_source.jsonl"
    client_source = root / "client_source.jsonl"
    server_csv = root / "server.csv"
    client_csv = root / "client.csv"
    input_commitment = root / "input_commitments.json"
    server_source.write_text('{"email":"a@example.com","campaign":"demo"}\n', encoding="utf-8")
    client_source.write_text('{"email":"a@example.com","amount":100}\n', encoding="utf-8")
    server_csv.write_text("email\nhash_a\n", encoding="utf-8")
    client_csv.write_text("email,amount\nhash_a,100\n", encoding="utf-8")
    input_commitment.write_text(
        json.dumps(
            {
                "schema": "pjc_input_commitment/v1",
                "job_id": "source-attestation-smoke",
                "token_scope": "scope",
                "token_key_version": "1",
                "normalize_version": "1",
                "normalizer_schema_version": "normalizer-schema/v1",
                "parties": {},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "server_source": server_source,
        "client_source": client_source,
        "server_csv": server_csv,
        "client_csv": client_csv,
        "input_commitment": input_commitment,
    }


def build_attestation(
    *,
    root: Path,
    key_path: Path | None,
    attestation_mode: str = "operator",
    signoff_status: str = "approved_dual",
    created_at_utc: str | None = None,
    reviewer_identity: str = "compliance_auditor_demo",
) -> tuple[Path, Path]:
    inputs = fixture_inputs(root)
    attestation = root / "source_attestation.json"
    manifest = root / "source_export_manifest.json"
    created_at_utc = created_at_utc or utc_now_iso()
    cmd = [
        sys.executable,
        str(BUILD_SCRIPT),
        "--output-attestation",
        str(attestation),
        "--output-export-manifest",
        str(manifest),
        "--job-id",
        "source-attestation-smoke",
        "--caller",
        "marketing_analyst_demo",
        "--tenant",
        "commerce_tenant",
        "--dataset",
        "orders_analytics",
        "--purpose",
        "campaign_measurement",
        "--source-system",
        "ecommerce_fact_import",
        "--approval-id",
        "approval-source-smoke",
        "--operator-identity",
        "privacy_operator_demo",
        "--reviewer-identity",
        reviewer_identity,
        "--signoff-status",
        signoff_status,
        "--attestation-mode",
        attestation_mode,
        "--server-source",
        str(inputs["server_source"]),
        "--client-source",
        str(inputs["client_source"]),
        "--server-bridge-input",
        str(inputs["server_csv"]),
        "--client-bridge-input",
        str(inputs["client_csv"]),
        "--input-commitment",
        str(inputs["input_commitment"]),
        "--created-at-utc",
        created_at_utc,
    ]
    if key_path is not None:
        cmd.extend(["--signing-key-path", str(key_path)])
    res = run(cmd)
    if res.returncode != 0:
        raise RuntimeError(f"build_source_attestation.py failed: {res.stderr or res.stdout}")
    return attestation, manifest


def verify_attestation(
    *,
    root: Path,
    attestation_path: Path,
    manifest_path: Path,
    strict: bool,
    require_signed_signoff: bool,
    require_dual_signoff: bool,
    max_age_hours: float = 0.0,
    dataset: str = "orders_analytics",
) -> dict[str, Any]:
    inputs = {
        "server_source": root / "server_source.jsonl",
        "client_source": root / "client_source.jsonl",
        "server_csv": root / "server.csv",
        "client_csv": root / "client.csv",
        "input_commitment": root / "input_commitments.json",
    }
    out = root / "source_truthfulness_report.json"
    cmd = [
        sys.executable,
        str(CHECK_SCRIPT),
        "--attestation",
        str(attestation_path),
        "--source-export-manifest",
        str(manifest_path),
        "--server-source",
        str(inputs["server_source"]),
        "--client-source",
        str(inputs["client_source"]),
        "--server-bridge-input",
        str(inputs["server_csv"]),
        "--client-bridge-input",
        str(inputs["client_csv"]),
        "--input-commitment",
        str(inputs["input_commitment"]),
        "--job-id",
        "source-attestation-smoke",
        "--caller",
        "marketing_analyst_demo",
        "--tenant",
        "commerce_tenant",
        "--dataset",
        dataset,
        "--purpose",
        "campaign_measurement",
        "--output",
        str(out),
    ]
    if strict:
        cmd.append("--strict")
    if require_signed_signoff:
        cmd.append("--require-signed-signoff")
    if require_dual_signoff:
        cmd.append("--require-dual-signoff")
    if max_age_hours > 0:
        cmd.extend(["--max-age-hours", str(max_age_hours)])
    res = run(cmd)
    if res.returncode not in {0, 2}:
        raise RuntimeError(f"check_source_attestation.py failed: {res.stderr or res.stdout}")
    payload = load_json(out)
    validate_value(payload, SOURCE_REPORT_SCHEMA)
    return payload


def record_case(cases: list[dict[str, Any]], *, name: str, ok: bool, report: dict[str, Any], detail: Any = None) -> None:
    cases.append(
        {
            "name": name,
            "status": "pass" if ok else "fail",
            "decision": report.get("decision"),
            "reason_code": report.get("reason_code"),
            "detail": detail,
        }
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke coverage for source attestation and source truthfulness gates.")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="source_attestation_smoke.") as tmp_raw:
        root = Path(tmp_raw)
        key_path = root / "signing_key.pem"
        write_key(key_path)

        # 1. Positive path.
        case_root = root / "case_allow"
        attestation, manifest = build_attestation(root=case_root, key_path=key_path)
        report = verify_attestation(root=case_root, attestation_path=attestation, manifest_path=manifest, strict=True, require_signed_signoff=True, require_dual_signoff=True, max_age_hours=168)
        record_case(cases, name="positive_allow", ok=report.get("decision") == "allow", report=report)

        # 2. Missing attestation.
        case_root = root / "case_missing"
        inputs = fixture_inputs(case_root)
        manifest = case_root / "source_export_manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        out = case_root / "missing_report.json"
        res = run(
            [
                sys.executable,
                str(CHECK_SCRIPT),
                "--attestation",
                str(case_root / "missing_attestation.json"),
                "--server-source",
                str(inputs["server_source"]),
                "--client-source",
                str(inputs["client_source"]),
                "--server-bridge-input",
                str(inputs["server_csv"]),
                "--client-bridge-input",
                str(inputs["client_csv"]),
                "--input-commitment",
                str(inputs["input_commitment"]),
                "--job-id",
                "source-attestation-smoke",
                "--caller",
                "marketing_analyst_demo",
                "--tenant",
                "commerce_tenant",
                "--dataset",
                "orders_analytics",
                "--purpose",
                "campaign_measurement",
                "--output",
                str(out),
            ]
        )
        if res.returncode not in {0, 2}:
            raise RuntimeError(f"missing-attestation verifier failed: {res.stderr or res.stdout}")
        report = load_json(out)
        record_case(cases, name="missing_attestation_rejected", ok=report.get("reason_code") == "source_attestation_missing", report=report)

        # 3. Hash mismatch.
        case_root = root / "case_hash_mismatch"
        attestation, manifest = build_attestation(root=case_root, key_path=key_path)
        (case_root / "client.csv").write_text("email,amount\nhash_a,999\n", encoding="utf-8")
        report = verify_attestation(root=case_root, attestation_path=attestation, manifest_path=manifest, strict=False, require_signed_signoff=False, require_dual_signoff=False)
        record_case(cases, name="hash_mismatch_rejected", ok=report.get("reason_code") == "bridge_input_hash_mismatch", report=report)

        # 4. Scope mismatch.
        case_root = root / "case_scope_mismatch"
        attestation, manifest = build_attestation(root=case_root, key_path=key_path)
        report = verify_attestation(root=case_root, attestation_path=attestation, manifest_path=manifest, strict=False, require_signed_signoff=False, require_dual_signoff=False, dataset="wrong_dataset")
        record_case(cases, name="scope_mismatch_rejected", ok=report.get("reason_code") == "attestation_scope_mismatch", report=report)

        # 5. Signed signoff missing.
        case_root = root / "case_unsigned"
        attestation, manifest = build_attestation(root=case_root, key_path=None, signoff_status="approved_dual")
        report = verify_attestation(root=case_root, attestation_path=attestation, manifest_path=manifest, strict=False, require_signed_signoff=True, require_dual_signoff=True)
        record_case(cases, name="signoff_missing_rejected", ok=report.get("reason_code") == "signoff_signature_invalid", report=report)

        # 6. Planned strict reject.
        case_root = root / "case_planned"
        attestation, manifest = build_attestation(root=case_root, key_path=key_path, attestation_mode="planned", signoff_status="approved_dual")
        report = verify_attestation(root=case_root, attestation_path=attestation, manifest_path=manifest, strict=True, require_signed_signoff=True, require_dual_signoff=True)
        record_case(cases, name="planned_strict_rejected", ok=report.get("reason_code") == "strict_mode_source_attestation_rejected", report=report)

        # 7. Local strict reject.
        case_root = root / "case_local"
        attestation, manifest = build_attestation(root=case_root, key_path=key_path, attestation_mode="local", signoff_status="approved_dual")
        report = verify_attestation(root=case_root, attestation_path=attestation, manifest_path=manifest, strict=True, require_signed_signoff=True, require_dual_signoff=True)
        record_case(cases, name="local_strict_rejected", ok=report.get("reason_code") == "strict_mode_source_attestation_rejected", report=report)

        # 8. Manual strict reject.
        case_root = root / "case_manual"
        attestation, manifest = build_attestation(root=case_root, key_path=key_path, attestation_mode="manual", signoff_status="approved_dual")
        report = verify_attestation(root=case_root, attestation_path=attestation, manifest_path=manifest, strict=True, require_signed_signoff=True, require_dual_signoff=True)
        record_case(cases, name="manual_strict_rejected", ok=report.get("reason_code") == "strict_mode_source_attestation_rejected", report=report)

        # 9. Stale strict reject.
        case_root = root / "case_stale"
        attestation, manifest = build_attestation(root=case_root, key_path=key_path, created_at_utc="2025-01-01T00:00:00Z")
        report = verify_attestation(root=case_root, attestation_path=attestation, manifest_path=manifest, strict=True, require_signed_signoff=True, require_dual_signoff=True, max_age_hours=24)
        record_case(cases, name="stale_strict_rejected", ok=report.get("reason_code") == "source_attestation_stale", report=report)

        # 10. Dual signoff same-identity reject.
        case_root = root / "case_same_identity_dual"
        try:
            build_attestation(
                root=case_root,
                key_path=key_path,
                signoff_status="approved_dual",
                reviewer_identity="privacy_operator_demo",
            )
            same_identity_ok = False
            same_identity_detail = "build unexpectedly succeeded"
        except RuntimeError as exc:
            same_identity_ok = "reviewer identity distinct from operator identity" in str(exc)
            same_identity_detail = str(exc)
        record_case(
            cases,
            name="dual_same_identity_rejected",
            ok=same_identity_ok,
            report={"decision": "deny", "reason_code": "signoff_identity_separation_invalid"},
            detail=same_identity_detail,
        )

        # 11. Dual signoff required but single-approved attestation reject.
        case_root = root / "case_single_signoff_when_dual_required"
        attestation, manifest = build_attestation(root=case_root, key_path=key_path, signoff_status="approved")
        report = verify_attestation(root=case_root, attestation_path=attestation, manifest_path=manifest, strict=True, require_signed_signoff=True, require_dual_signoff=True)
        record_case(cases, name="dual_required_single_signoff_rejected", ok=report.get("reason_code") == "signoff_identity_separation_invalid", report=report)

    passed = sum(1 for item in cases if item["status"] == "pass")
    payload = {
        "schema": SCHEMA,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if passed == len(cases) else "fail",
        "total": len(cases),
        "passed": passed,
        "cases": cases,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        write_json(Path(args.output).resolve(), payload)
    print(text)
    return 0 if payload["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
