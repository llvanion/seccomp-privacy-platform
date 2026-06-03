#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import hashlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_DIR = REPO_ROOT / "bridge"
VALIDATE_BRIDGE_JOB = REPO_ROOT / "a-psi" / "moduleA_psi" / "scripts" / "validate_bridge_job.py"
PREFLIGHT = REPO_ROOT / "scripts" / "preflight_pjc_job.py"
LIMITS = REPO_ROOT / "config" / "pjc_resource_limits.example.json"
SERVER_SOURCE = REPO_ROOT / "sse" / "examples" / "bridge_server_records.jsonl"
CLIENT_SOURCE = REPO_ROOT / "sse" / "examples" / "bridge_client_records.jsonl"


def run(cmd: list[str], *, cwd: Path = REPO_ROOT, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def expect_ok(cmd: list[str], *, cwd: Path = REPO_ROOT, env: dict[str, str] | None = None) -> None:
    result = run(cmd, cwd=cwd, env=env)
    if result.returncode != 0:
        raise SystemExit(f"[ERROR] command failed unexpectedly: {cmd}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")


def expect_fail(cmd: list[str], expected: str, *, cwd: Path = REPO_ROOT, env: dict[str, str] | None = None) -> None:
    result = run(cmd, cwd=cwd, env=env)
    if result.returncode == 0:
        raise SystemExit(f"[ERROR] command passed unexpectedly: {cmd}\nSTDOUT:\n{result.stdout}")
    combined = result.stdout + result.stderr
    if expected not in combined:
        raise SystemExit(
            f"[ERROR] command failed without expected text {expected!r}: {cmd}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_bridge_job(out_dir: Path) -> None:
    env = dict(os.environ)
    env["BRIDGE_TOKEN_SECRET"] = "commitment-smoke-secret"
    expect_ok(
        [
            "cargo",
            "run",
            "--",
            "prepare-job",
            "--server-input",
            str(SERVER_SOURCE),
            "--server-input-format",
            "jsonl",
            "--server-join-key-column",
            "email",
            "--server-normalizer",
            "email",
            "--client-input",
            str(CLIENT_SOURCE),
            "--client-input-format",
            "jsonl",
            "--client-join-key-column",
            "email",
            "--client-value-column",
            "amount",
            "--client-value-mode",
            "raw-int",
            "--client-value-max",
            "1000000",
            "--client-normalizer",
            "email",
            "--out-dir",
            str(out_dir),
            "--job-id",
            "commitment_smoke_job",
            "--token-scope",
            "commitment-smoke-scope",
            "--token-secret-env",
            "BRIDGE_TOKEN_SECRET",
            "--audit-log",
            str(out_dir / "bridge_audit.jsonl"),
        ],
        cwd=BRIDGE_DIR,
        env=env,
    )


def preflight_cmd(job_dir: Path, out_file: Path) -> list[str]:
    return [
        "python3",
        str(PREFLIGHT),
        "--resource-limits",
        str(LIMITS),
        "--server-csv",
        str(job_dir / "server.csv"),
        "--client-csv",
        str(job_dir / "client.csv"),
        "--caller",
        "auto_demo",
        "--tenant-id",
        "demo_tenant",
        "--dataset-id",
        "bridge_demo_dataset",
        "--purpose",
        "bridge_token",
        "--job-id",
        "commitment_smoke_job",
        "--input-commitment",
        str(job_dir / "input_commitments.json"),
        "--job-meta",
        str(job_dir / "job_meta.json"),
        "--require-input-commitment",
        "--output",
        str(out_file),
        "--assert-allow",
    ]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pjc_input_commitment.") as tmp:
        root = Path(tmp)
        job_dir = root / "bridge_job"
        build_bridge_job(job_dir)
        expect_ok(["python3", str(VALIDATE_BRIDGE_JOB), "--job-dir", str(job_dir)])
        expect_ok(preflight_cmd(job_dir, root / "preflight_ok.json"))

        commitment = json.loads((job_dir / "input_commitments.json").read_text(encoding="utf-8"))
        if commitment.get("schema") != "pjc_input_commitment/v1":
            raise SystemExit("[ERROR] input commitment schema missing")
        if (job_dir / "input_commitments.json").stat().st_size <= 0:
            raise SystemExit("[ERROR] input commitment file is empty")

        with (job_dir / "server.csv").open("a", encoding="utf-8") as f:
            f.write("tampered-token\n")
        expect_fail(
            ["python3", str(VALIDATE_BRIDGE_JOB), "--job-dir", str(job_dir)],
            "input_sizes.exposure_n mismatch",
        )
        expect_fail(preflight_cmd(job_dir, root / "preflight_tampered_server.json"), "input_commitment_mismatch")

        build_bridge_job(job_dir)
        payload = json.loads((job_dir / "input_commitments.json").read_text(encoding="utf-8"))
        payload["parties"]["client"]["output_csv_sha256"] = "0" * 64
        (job_dir / "input_commitments.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        expect_fail(
            ["python3", str(VALIDATE_BRIDGE_JOB), "--job-dir", str(job_dir)],
            "input_commitment_sha256 mismatch",
        )
        expect_fail(
            preflight_cmd(job_dir, root / "preflight_tampered_commitment.json"),
            "input commitment sha256 does not match job_meta",
        )

        build_bridge_job(job_dir)
        commitment_path = job_dir / "input_commitments.json"
        payload = json.loads(commitment_path.read_text(encoding="utf-8"))
        client_party = payload["parties"]["client"]
        with (job_dir / "client.csv").open("a", encoding="utf-8") as f:
            f.write("f" * 64 + ",-1\n")
        client_party["output_csv_sha256"] = sha256_file(job_dir / "client.csv")
        client_party["output_row_count"] += 1
        client_party["value_summary"]["sum"] -= 1
        client_party["value_summary"]["min"] = -1
        client_party["value_summary"]["non_negative"] = False
        commitment_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        job_meta = json.loads((job_dir / "job_meta.json").read_text(encoding="utf-8"))
        job_meta["input_sizes"]["purchase_n"] += 1
        job_meta["inputs"]["input_commitment_sha256"] = sha256_file(commitment_path)
        (job_dir / "job_meta.json").write_text(json.dumps(job_meta, indent=2) + "\n", encoding="utf-8")
        expect_fail(
            ["python3", str(VALIDATE_BRIDGE_JOB), "--job-dir", str(job_dir)],
            "negative values are not allowed",
        )
        expect_fail(
            preflight_cmd(job_dir, root / "preflight_negative_value.json"),
            "value_policy_violation",
        )

        build_bridge_job(job_dir)
        commitment_path = job_dir / "input_commitments.json"
        payload = json.loads(commitment_path.read_text(encoding="utf-8"))
        client_party = payload["parties"]["client"]
        with (job_dir / "client.csv").open("a", encoding="utf-8") as f:
            f.write("e" * 64 + ",1000001\n")
        client_party["output_csv_sha256"] = sha256_file(job_dir / "client.csv")
        client_party["output_row_count"] += 1
        client_party["value_summary"]["sum"] += 1000001
        client_party["value_summary"]["max"] = 1000001
        commitment_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        job_meta = json.loads((job_dir / "job_meta.json").read_text(encoding="utf-8"))
        job_meta["input_sizes"]["purchase_n"] += 1
        job_meta["inputs"]["input_commitment_sha256"] = sha256_file(commitment_path)
        (job_dir / "job_meta.json").write_text(json.dumps(job_meta, indent=2) + "\n", encoding="utf-8")
        expect_fail(
            ["python3", str(VALIDATE_BRIDGE_JOB), "--job-dir", str(job_dir)],
            "max 1000001 > 1000000",
        )
        expect_fail(
            preflight_cmd(job_dir, root / "preflight_over_max_value.json"),
            "value_policy_violation",
        )

        build_bridge_job(job_dir)
        commitment_path = job_dir / "input_commitments.json"
        payload = json.loads(commitment_path.read_text(encoding="utf-8"))
        payload["token_scope"] = "attacker-scope"
        commitment_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        job_meta = json.loads((job_dir / "job_meta.json").read_text(encoding="utf-8"))
        job_meta["inputs"]["input_commitment_sha256"] = sha256_file(commitment_path)
        (job_dir / "job_meta.json").write_text(json.dumps(job_meta, indent=2) + "\n", encoding="utf-8")
        expect_fail(
            ["python3", str(VALIDATE_BRIDGE_JOB), "--job-dir", str(job_dir)],
            "input commitment token_scope mismatch",
        )
        expect_fail(
            preflight_cmd(job_dir, root / "preflight_token_scope_mismatch.json"),
            "input commitment token_scope does not match job_meta",
        )

        build_bridge_job(job_dir)
        commitment_path = job_dir / "input_commitments.json"
        payload = json.loads(commitment_path.read_text(encoding="utf-8"))
        payload["parties"]["client"]["normalizer"] = "identity"
        commitment_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        job_meta = json.loads((job_dir / "job_meta.json").read_text(encoding="utf-8"))
        job_meta["inputs"]["input_commitment_sha256"] = sha256_file(commitment_path)
        (job_dir / "job_meta.json").write_text(json.dumps(job_meta, indent=2) + "\n", encoding="utf-8")
        expect_fail(
            ["python3", str(VALIDATE_BRIDGE_JOB), "--job-dir", str(job_dir)],
            "input commitment client.normalizer mismatch",
        )
        expect_fail(
            preflight_cmd(job_dir, root / "preflight_normalizer_mismatch.json"),
            "input commitment client.normalizer does not match job_meta",
        )

        build_bridge_job(job_dir)
        commitment_path = job_dir / "input_commitments.json"
        payload = json.loads(commitment_path.read_text(encoding="utf-8"))
        payload["normalizer_schema_version"] = "normalizer-schema/v999"
        commitment_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        job_meta = json.loads((job_dir / "job_meta.json").read_text(encoding="utf-8"))
        job_meta["inputs"]["input_commitment_sha256"] = sha256_file(commitment_path)
        (job_dir / "job_meta.json").write_text(json.dumps(job_meta, indent=2) + "\n", encoding="utf-8")
        expect_fail(
            ["python3", str(VALIDATE_BRIDGE_JOB), "--job-dir", str(job_dir)],
            "input commitment normalizer_schema_version mismatch",
        )
        expect_fail(
            preflight_cmd(job_dir, root / "preflight_normalizer_schema_mismatch.json"),
            "input commitment normalizer_schema_version does not match job_meta",
        )

    print("[ok] PJC input commitment gate verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
