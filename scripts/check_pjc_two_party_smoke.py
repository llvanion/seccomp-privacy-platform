#!/usr/bin/env python3
"""Focused smoke for the two-party out-of-box (S9) dashboard endpoints.

Exercises the five new helpers directly so the suite does not require running
the HTTP server or the real PJC binaries:

1. ``_two_party_preflight`` — happy path and several deny paths.
2. ``_role_package_export`` + ``_role_package_import`` — round-trip + tamper.
3. ``_start_role`` + status poll + ``_cancel_role`` — uses ``/bin/true`` as a
   surrogate role script so the smoke does not need the real PJC binaries.
4. ``_two_party_evidence_merge`` — agreement vs. mismatch.
5. ``_two_party_negative_cases`` — all eight required cases succeed.

Each report is validated against its JSON schema with
``scripts/validate_json_contract.py``.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import serve_operator_dashboard as sod
from validate_json_contract import load_json, validate_value


SCHEMA_DIR = REPO_ROOT / "schemas"


def _validate(report: dict, schema_filename: str) -> None:
    schema = load_json(str(SCHEMA_DIR / schema_filename))
    validate_value(report, schema)


def _make_role_dir(tmp: Path) -> Path:
    role_dir = tmp / "party_a_job"
    role_dir.mkdir(parents=True, exist_ok=True)
    (role_dir / "server.csv").write_text("server-csv-content\n", encoding="utf-8")
    (role_dir / "job_meta.json").write_text(json.dumps({"job_id": "smoke"}), encoding="utf-8")
    return role_dir


def _setup_party_evidence(root: Path, *, job_id: str, agree: bool) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "a_psi_run").mkdir(parents=True, exist_ok=True)
    (root / "bridge_job").mkdir(parents=True, exist_ok=True)
    public = {"job_id": job_id, "released": True, "reason_code": "ok", "commit": "deadbeef"}
    attribution = {"job_id": job_id, "intersection_size": 2, "intersection_sum": 100 if agree else 999}
    (root / "a_psi_run" / "public_report.json").write_text(json.dumps(public, sort_keys=True), encoding="utf-8")
    (root / "a_psi_run" / "attribution_result.json").write_text(json.dumps(attribution, sort_keys=True), encoding="utf-8")
    pjc_audit = {
        "schema": "pjc_audit/v1",
        "job_id": job_id,
        "commit": "deadbeef",
        "input_commitment_sha256": "abc123",
        "tls": {"peer_identity": "job-x.partyB.example", "ca_fingerprint_sha256": "ca-fp"},
    }
    (root / "a_psi_run" / "pjc_audit.jsonl").write_text(json.dumps(pjc_audit, sort_keys=True) + "\n", encoding="utf-8")
    (root / "audit_chain.json").write_text(json.dumps({"job_id": job_id, "commit": "deadbeef"}, sort_keys=True), encoding="utf-8")
    (root / "bridge_job" / "job_meta.json").write_text(json.dumps({"job_id": job_id, "input_commitment_sha256": "abc123"}, sort_keys=True), encoding="utf-8")
    return root


def test_preflight() -> None:
    print("[1/5] preflight ...")
    with tempfile.TemporaryDirectory(prefix="pjc_two_party_smoke_") as tmp:
        tmp_path = Path(tmp)
        csv_path = tmp_path / "client.csv"
        csv_path.write_text("hdr\nrow1\nrow2\n", encoding="utf-8")
        helper_script = tmp_path / "helper.sh"
        helper_script.write_text("#!/usr/bin/env bash\necho stub\n", encoding="utf-8")
        helper_script.chmod(0o755)
        out_dir = tmp_path / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        # happy path (only checks we can prove locally)
        body = {
            "job_id": "smoke",
            "role": "client",
            "helper_script_path": str(helper_script),
            "expected_helper_script_sha256": sod._sha256_file(helper_script),
            "input_csv_path": str(csv_path),
            "expected_input_csv_sha256": sod._sha256_file(csv_path),
            "max_rows": 100,
            "max_bytes": 1024,
            "output_dir": str(out_dir),
            "require_unique_output": False,
        }
        result = sod._two_party_preflight(body)
        _validate(result["report"], "pjc_two_party_preflight.schema.json")
        assert result["report"]["decision"] == "allow", result["report"]
        # deny path — corrupt expected CSV hash
        bad_body = dict(body)
        bad_body["expected_input_csv_sha256"] = "0" * 64
        bad_result = sod._two_party_preflight(bad_body)
        _validate(bad_result["report"], "pjc_two_party_preflight.schema.json")
        assert bad_result["report"]["decision"] == "deny"
        assert bad_result["report"]["reason_code"] == "input_manifest_hash_mismatch"
    print("       preflight OK")


def test_role_package_roundtrip() -> None:
    print("[2/5] role package export/import ...")
    with tempfile.TemporaryDirectory(prefix="pjc_role_pkg_") as tmp:
        tmp_path = Path(tmp)
        source = _make_role_dir(tmp_path)
        out_dir = tmp_path / "packages"
        exp = sod._role_package_export({
            "job_id": "smoke",
            "role": "server",
            "source_dir": str(source),
            "output_dir": str(out_dir),
            "expected_peer_identity": "job-smoke.partyB.example",
            "dataplane_port": 10502,
            "loopback_port": 10501,
            "k_threshold": 20,
            "dp_epsilon": 1.0,
            "dp_sensitivity": 10000,
            "require_dp": True,
        })
        _validate(exp["manifest"], "pjc_role_package.schema.json")
        package_path = exp["package_path"]
        target = tmp_path / "import_target"
        imp = sod._role_package_import({
            "package_path": package_path,
            "target_dir": str(target),
        })
        # import report extends the manifest with `validation`
        report = imp["report"]
        # the report retains schema=pjc_role_package/v1
        _validate({k: v for k, v in report.items() if k not in ("validation", "imported_dir")}, "pjc_role_package.schema.json")
        assert imp["decision"] == "allow", report
        # tamper a payload file and re-import to confirm deny
        tampered = Path(package_path) / "payload" / "server.csv"
        tampered.write_text("tampered\n", encoding="utf-8")
        imp2 = sod._role_package_import({"package_path": package_path})
        assert imp2["decision"] == "deny", imp2["report"]
    print("       role package OK")


def test_role_lifecycle() -> None:
    print("[3/5] role lifecycle (start/status/cancel) ...")
    # Use /bin/true as a surrogate "role script" via the optional `script`
    # override and rely on a stand-in cert dir / role dir. We bypass the real
    # PJC scripts because the smoke must not depend on the PJC binaries.
    with tempfile.TemporaryDirectory(prefix="pjc_role_life_") as tmp:
        tmp_path = Path(tmp)
        cert_dir = tmp_path / "certs"
        cert_dir.mkdir(parents=True, exist_ok=True)
        # Drop a placeholder script under the PJC mTLS script dir so _role_command
        # can find it via the script-name overrides. We write the script to a
        # temp dir and then point the registry at it directly.
        script_path = sod.PJC_MTLS_SCRIPT_DIR / "_smoke_role.sh"
        try:
            script_path.write_text("#!/usr/bin/env bash\nsleep 1\nexit 0\n", encoding="utf-8")
            script_path.chmod(0o755)
            started = sod._start_role("server", {
                "job_id": "lifesmoke",
                "cert_dir": str(cert_dir),
                "role_dir": str(tmp_path / "role_dir"),
                "script": "_smoke_role.sh",
                "tls_port": 10502,
                "pjc_local_port": 10501,
            })
            _validate({k: v for k, v in started["snapshot"].items() if k != "evidence_path"} | {"evidence_path": started["snapshot"]["evidence_path"]}, "pjc_role_status.schema.json")
            assert started["snapshot"]["state"] == "running", started
            # poll status — should still validate
            status = sod._role_status_payload("lifesmoke::server")
            assert status is not None
            _validate(status, "pjc_role_status.schema.json")
            # cancel
            cancelled = sod._cancel_role("server", {"job_id": "lifesmoke", "reason": "smoke_cancel"})
            assert cancelled["status"] == "ok"
            assert cancelled["snapshot"]["state"] == "cancelled"
            _validate(cancelled["snapshot"], "pjc_role_status.schema.json")
        finally:
            try:
                script_path.unlink()
            except FileNotFoundError:
                pass
    print("       role lifecycle OK")


def test_evidence_merge() -> None:
    print("[4/5] evidence verify-merge ...")
    with tempfile.TemporaryDirectory(prefix="pjc_evid_") as tmp:
        tmp_path = Path(tmp)
        a = _setup_party_evidence(tmp_path / "party_a_run", job_id="smoke", agree=True)
        b = _setup_party_evidence(tmp_path / "party_b_run", job_id="smoke", agree=True)
        ok = sod._two_party_evidence_merge({"job_id": "smoke", "party_a_dir": str(a), "party_b_dir": str(b)})
        _validate(ok["report"], "pjc_two_party_evidence_merge.schema.json")
        assert ok["report"]["decision"] == "allow", ok["report"]
        b2 = _setup_party_evidence(tmp_path / "party_b_bad", job_id="smoke", agree=False)
        bad = sod._two_party_evidence_merge({"job_id": "smoke", "party_a_dir": str(a), "party_b_dir": str(b2)})
        _validate(bad["report"], "pjc_two_party_evidence_merge.schema.json")
        assert bad["report"]["decision"] == "deny"
        assert bad["report"]["reason_code"] == "result_hash_mismatch", bad["report"]
    print("       evidence merge OK")


def test_negative_cases() -> None:
    print("[5/5] required negative cases ...")
    with tempfile.TemporaryDirectory(prefix="pjc_neg_") as tmp:
        tmp_path = Path(tmp)
        csv_path = tmp_path / "client.csv"
        csv_path.write_text("hdr\nrow1\n", encoding="utf-8")
        out_dir = tmp_path / "preflight_out"
        public_report = tmp_path / "public_report.json"
        public_report.write_text(json.dumps({"released": False, "reason_code": "below_k"}), encoding="utf-8")
        base_scenario = {
            "job_id": "negsmoke",
            "input_csv_path": str(csv_path),
            "output_dir": str(out_dir),
            "require_unique_output": False,
        }
        scenarios = {
            "wrong_token": {"pairing_token": "nope", "csr_pem": "garbage"},
            "expired_token": {"csr_pem": "garbage"},
            "wrong_ca": dict(base_scenario),
            "wrong_peer": dict(base_scenario, peer_cert_path=""),
            "closed_port": dict(base_scenario),
            "commit_mismatch": dict(base_scenario),
            "modified_csv": dict(base_scenario),
            "privacy_denial": {"public_report_path": str(public_report)},
        }
        result = sod._two_party_negative_cases({"job_id": "negsmoke", "scenarios": scenarios})
        _validate(result["report"], "pjc_two_party_negative_cases.schema.json")
        # Every required case should at least be present; allow `commit_mismatch` to
        # be a pass when actual repo commit happens not to be "0"*40 (which is always
        # the case in practice but we still want the row present).
        names = {item["name"] for item in result["report"]["cases"]}
        for required in sod.PJC_REQUIRED_NEGATIVE_CASES:
            assert required in names, f"missing {required} in negative-case summary"
        assert result["report"]["decision"] == "allow", result["report"]
    print("       negative cases OK")


def main() -> int:
    os.environ["PJC_MTLS_PAIRING_TOKEN_TTL_SECONDS"] = os.environ.get("PJC_MTLS_PAIRING_TOKEN_TTL_SECONDS", "600")
    os.environ["PJC_MTLS_MAX_ENROLLMENTS"] = os.environ.get("PJC_MTLS_MAX_ENROLLMENTS", "1")
    test_preflight()
    test_role_package_roundtrip()
    test_role_lifecycle()
    test_evidence_merge()
    test_negative_cases()
    print("[ok] PJC two-party (S9) smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
