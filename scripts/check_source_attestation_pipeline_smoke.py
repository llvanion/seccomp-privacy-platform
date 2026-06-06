#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from validate_json_contract import load_json as load_schema_json, validate_value


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = load_schema_json(str(REPO_ROOT / "schemas" / "source_attestation_pipeline_smoke.schema.json"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def make_key(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="End-to-end pipeline smoke for source attestation governance wiring.")
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    checks: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="source_att_pipeline_smoke.") as tmp_raw:
        root = Path(tmp_raw)
        out_base = root / "out"
        key_path = root / "source_attestation_ed25519.pem"
        fake_pjc_path = root / "fake_run_pjc.sh"
        release_policy_config = root / "release_policy_gate_source_attestation.json"

        make_key(key_path)
        fake_pjc_path.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "mkdir -p \"$OUT_DIR\"\n"
            "cat > \"$OUT_DIR/attribution_result.json\" <<'JSON'\n"
            "{\n"
            "  \"job_id\": \"source_attestation_pipeline_smoke\",\n"
            "  \"intersection_size\": 2,\n"
            "  \"intersection_sum\": 425\n"
            "}\n"
            "JSON\n",
            encoding="utf-8",
        )
        fake_pjc_path.chmod(0o755)
        write_json(
            release_policy_config,
            {
                "schema": "release_policy_gate_config/v1",
                "require_dp": True,
                "min_dp_epsilon": 0.1,
                "max_dp_epsilon": 5.0,
                "min_k": 1,
                "require_privacy_budget": False,
                "budget_ledger_path": None,
                "duplicate_query_denied": True,
                "require_public_report_redaction": False,
                "require_source_attestation": True,
                "require_signed_signoff": True,
                "require_dual_signoff": True,
                "require_bound_input_commitment": True,
                "strict_source_attestation": True,
                "max_source_attestation_age_hours": 168,
                "require_pjc_evidence_merge": False,
                "require_external_anchor": False,
                "allowed_deny_reason_codes": [
                    "below_k",
                    "below_min_rows",
                    "rate_limit_exceeded",
                    "privacy_budget_exhausted",
                    "privacy_budget_duplicate_query",
                    "privacy_budget_near_duplicate",
                    "privacy_budget_bucket_probe",
                    "privacy_budget_missing_scope",
                    "privacy_budget_config_missing",
                ],
            },
        )
        env = dict(**__import__("os").environ)
        env["HOME"] = str(root / "home")
        (Path(env["HOME"]) / ".sse" / "log").mkdir(parents=True, exist_ok=True)
        env["RUN_PJC_SH"] = str(fake_pjc_path)
        bridge_bin = (REPO_ROOT / "bridge" / "target" / "debug" / "bridge").resolve()
        env["BRIDGE_BIN"] = str(bridge_bin) if bridge_bin.is_file() else "cargo run --"
        result = run(
            [
                "bash",
                "scripts/run_sse_bridge_pipeline.sh",
                "--server-source",
                "sse/examples/bridge_server_records.jsonl",
                "--client-source",
                "sse/examples/bridge_client_records.jsonl",
                "--server-source-format",
                "jsonl",
                "--client-source-format",
                "jsonl",
                "--server-join-key-field",
                "email",
                "--client-join-key-field",
                "email",
                "--client-value-field",
                "amount",
                "--server-normalizer",
                "email",
                "--client-normalizer",
                "email",
                "--client-value-mode",
                "raw-int",
                "--client-value-min",
                "0",
                "--client-value-max",
                "1000000",
                "--client-allowed-value-field",
                "amount",
                "--client-value-unit",
                "minor_currency_unit",
                "--client-value-currency",
                "USD",
                "--server-filter",
                "campaign=demo",
                "--client-filter",
                "campaign=demo",
                "--token-scope",
                "source-attestation-pipeline-smoke-scope",
                "--token-secret",
                "local-dev-secret",
                "--job-id",
                "source_attestation_pipeline_smoke",
                "--out-base",
                str(out_base),
                "--caller",
                "auto_demo",
                "--tenant-id",
                "demo_tenant",
                "--dataset-id",
                "bridge_demo_dataset",
                "--source-system",
                "ecommerce_fact_import",
                "--source-attestation-mode",
                "operator",
                "--source-attestation-approval-id",
                "approval-source-attestation-pipeline-smoke",
                "--source-attestation-operator-identity",
                "privacy_operator_demo",
                "--source-attestation-reviewer-identity",
                "compliance_auditor_demo",
                "--source-attestation-signoff-status",
                "approved_dual",
                "--source-attestation-signing-key-path",
                str(key_path),
                "--sse-export-policy-config",
                "sse/config/export_policy.example.json",
                "--release-policy-gate-config",
                str(release_policy_config),
                "--require-dp",
                "--dp-epsilon",
                "1.0",
                "--dp-sensitivity",
                "500",
                "--k",
                "1",
                "--n",
                "5",
            ],
            env=env,
        )
        if result.returncode != 0:
            payload = {
                "schema": "source_attestation_pipeline_smoke/v1",
                "generated_at_utc": utc_now_iso(),
                "status": "fail",
                "out_base": str(out_base),
                "checks": [
                    {
                        "name": "pipeline_run",
                        "status": "fail",
                        "detail": {
                            "returncode": result.returncode,
                            "stdout": result.stdout,
                            "stderr": result.stderr,
                        },
                    }
                ],
            }
            if args.output:
                write_json(Path(args.output).resolve(), payload)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 2

        a_psi = out_base / "a_psi_run"
        attestation = load_json(a_psi / "source_attestation.json")
        truthfulness = load_json(a_psi / "source_truthfulness_report.json")
        public_report = load_json(a_psi / "public_report.json")
        release_gate = load_json(a_psi / "release_policy_gate.json")
        release_governance = load_json(a_psi / "release_governance_report.json")
        audit_chain = load_json(out_base / "audit_chain.json")
        policy_audit = json.loads((a_psi / "audit_log.jsonl").read_text(encoding="utf-8").splitlines()[-1])

        def check(name: str, ok: bool, detail: object) -> None:
            checks.append({"name": name, "status": "ok" if ok else "fail", "detail": detail})

        attestation_sha = sha256(a_psi / "source_attestation.json")
        truthfulness_sha = sha256(a_psi / "source_truthfulness_report.json")
        check("truthfulness_allow", truthfulness.get("decision") == "allow", truthfulness.get("reason_code"))
        check("release_gate_allow", release_gate.get("decision") == "allow", release_gate.get("reason_code"))
        check("release_governance_ok", release_governance.get("status") == "ok", release_governance.get("summary"))
        check("attestation_signed", attestation.get("signature_algorithm") == "ed25519", attestation.get("signature_algorithm"))
        check(
            "public_report_governance_bound",
            (public_report.get("governance") or {}).get("source_attestation_sha256") == attestation_sha
            and (public_report.get("governance") or {}).get("source_truthfulness_report_sha256") == truthfulness_sha,
            public_report.get("governance"),
        )
        check(
            "policy_audit_governance_bound",
            (policy_audit.get("governance") or {}).get("source_attestation_sha256") == attestation_sha
            and (policy_audit.get("governance") or {}).get("input_commitment_sha256") == attestation.get("input_commitment_sha256"),
            policy_audit.get("governance"),
        )
        check(
            "audit_chain_embeds_artifacts",
            isinstance(audit_chain.get("source_attestation"), dict)
            and isinstance(audit_chain.get("source_truthfulness_report"), dict)
            and isinstance(audit_chain.get("release_governance_report"), dict),
            {
                "source_attestation": bool(audit_chain.get("source_attestation")),
                "source_truthfulness_report": bool(audit_chain.get("source_truthfulness_report")),
                "release_governance_report": bool(audit_chain.get("release_governance_report")),
            },
        )

    payload = {
        "schema": "source_attestation_pipeline_smoke/v1",
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if all(item["status"] == "ok" for item in checks) else "fail",
        "out_base": str(out_base),
        "checks": checks,
    }
    validate_value(payload, SCHEMA)
    if args.output:
        write_json(Path(args.output).resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
