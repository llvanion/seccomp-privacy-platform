#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from verify_audit_bundle import verify_audit_bundle  # noqa: E402

SCHEMA_ID = "audit_tamper_resistance/v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def flip_byte_at(path: Path, offset: int) -> tuple[int, int]:
    data = bytearray(path.read_bytes())
    if offset < 0 or offset >= len(data):
        raise ValueError(f"offset {offset} out of range for file of length {len(data)}")
    original = data[offset]
    mutated = original ^ 0x01
    data[offset] = mutated
    path.write_bytes(bytes(data))
    return original, mutated


def restore_bytes(path: Path, original: bytes) -> None:
    path.write_bytes(original)


def find_value_offset(path: Path, key: str) -> int | None:
    """Locate a content byte inside the value of `key` for top-level JSON objects.

    Returns the absolute byte offset of a non-quote byte inside the value; None if the
    key is absent or its value is not a non-empty string.
    """
    raw_bytes = path.read_bytes()
    raw_text = raw_bytes.decode("utf-8")
    payload = json.loads(raw_text)
    if not isinstance(payload, dict) or key not in payload:
        return None
    value = payload[key]
    if not isinstance(value, str) or not value:
        return None
    needle = f'"{key}"'
    key_idx = raw_text.find(needle)
    if key_idx < 0:
        return None
    after_key = key_idx + len(needle)
    cursor = after_key
    while cursor < len(raw_text) and raw_text[cursor] != '"':
        cursor += 1
    if cursor >= len(raw_text):
        return None
    value_start = cursor + 1
    value_end = raw_text.find('"', value_start)
    if value_end < 0 or value_end <= value_start:
        return None
    target_index = value_start + min(max((value_end - value_start) // 2, 0), max(value_end - value_start - 1, 0))
    return len(raw_text[:target_index].encode("utf-8"))


def midfile_offset(path: Path) -> int:
    raw = path.read_bytes()
    return max(0, len(raw) // 2)


def run_verify(audit_chain_path: Path, audit_seal_path: Path, *, hmac_key_env: str, job_id: str) -> dict[str, Any]:
    """Wrap verify_audit_bundle so the boolean detected/exception logic is uniform."""
    try:
        audit_chain, audit_seal, audit_chain_sha256, audit_seal_sha256, signature_verified = verify_audit_bundle(
            audit_chain_path=str(audit_chain_path),
            audit_seal_path=str(audit_seal_path),
            job_id=job_id,
            hmac_key_env=hmac_key_env,
        )
        return {
            "raised": False,
            "error_class": None,
            "error_message": None,
            "audit_chain_sha256": audit_chain_sha256,
            "audit_seal_sha256": audit_seal_sha256,
            "signature_verified": signature_verified,
        }
    except Exception as exc:
        return {
            "raised": True,
            "error_class": type(exc).__name__,
            "error_message": str(exc),
            "audit_chain_sha256": None,
            "audit_seal_sha256": None,
            "signature_verified": None,
        }


def build_scenarios(audit_chain_path: Path, audit_seal_path: Path) -> list[dict[str, Any]]:
    """Build the stable scenario set.

    Each scenario must target a byte that the verifier's own integrity logic can
    detect. For audit_chain.json the verifier re-hashes the entire file, so any
    mutation is reliable. For audit_chain.seal.json only fields that participate in
    the integrity check are reliable (artifact_sha256, job_id; signature when present);
    other fields like artifact_file or ts_utc are not protected, so we deliberately
    skip them.
    """
    candidates: list[tuple[str, str, Path, str, int | None]] = [
        (
            "audit_chain_correlation_id_bit_flip",
            "audit_chain",
            audit_chain_path,
            "value_byte_inside_correlation_id",
            find_value_offset(audit_chain_path, "correlation_id"),
        ),
        (
            "audit_chain_job_id_bit_flip",
            "audit_chain",
            audit_chain_path,
            "value_byte_inside_job_id",
            find_value_offset(audit_chain_path, "job_id"),
        ),
        (
            "audit_chain_midfile_bit_flip",
            "audit_chain",
            audit_chain_path,
            "midfile_offset",
            midfile_offset(audit_chain_path),
        ),
        (
            "audit_seal_artifact_sha256_bit_flip",
            "audit_seal",
            audit_seal_path,
            "value_byte_inside_artifact_sha256",
            find_value_offset(audit_seal_path, "artifact_sha256"),
        ),
        (
            "audit_seal_job_id_bit_flip",
            "audit_seal",
            audit_seal_path,
            "value_byte_inside_job_id",
            find_value_offset(audit_seal_path, "job_id"),
        ),
        (
            "audit_seal_signature_bit_flip",
            "audit_seal",
            audit_seal_path,
            "value_byte_inside_signature",
            find_value_offset(audit_seal_path, "signature"),
        ),
    ]
    scenarios: list[dict[str, Any]] = []
    for name, target, path, hint, offset in candidates:
        if offset is None:
            continue
        scenarios.append(
            {
                "name": name,
                "target": target,
                "path": str(path),
                "offset_hint": hint,
                "offset": offset,
            }
        )
    return scenarios


def execute_scenarios(
    *,
    audit_chain_path: Path,
    audit_seal_path: Path,
    job_id: str,
    hmac_key_env: str,
    scenarios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    chain_original = audit_chain_path.read_bytes()
    seal_original = audit_seal_path.read_bytes()

    executed: list[dict[str, Any]] = []
    try:
        for scenario in scenarios:
            target = scenario["target"]
            target_path = audit_chain_path if target == "audit_chain" else audit_seal_path
            try:
                original, mutated = flip_byte_at(target_path, scenario["offset"])
                outcome = run_verify(
                    audit_chain_path,
                    audit_seal_path,
                    hmac_key_env=hmac_key_env,
                    job_id=job_id,
                )
            finally:
                restore_bytes(audit_chain_path, chain_original)
                restore_bytes(audit_seal_path, seal_original)
            detected = bool(outcome["raised"])
            executed.append(
                {
                    **scenario,
                    "original_byte": original,
                    "mutated_byte": mutated,
                    "detected": detected,
                    "verifier_raised": outcome["raised"],
                    "error_class": outcome["error_class"],
                    "error_message": outcome["error_message"],
                    "signature_verified_after_tamper": outcome["signature_verified"],
                }
            )
    finally:
        if audit_chain_path.read_bytes() != chain_original:
            restore_bytes(audit_chain_path, chain_original)
        if audit_seal_path.read_bytes() != seal_original:
            restore_bytes(audit_seal_path, seal_original)
    return executed


def post_restore_baseline_check(
    audit_chain_path: Path,
    audit_seal_path: Path,
    *,
    job_id: str,
    hmac_key_env: str,
    expected_chain_sha256: str,
    expected_seal_sha256: str,
) -> dict[str, Any]:
    chain_now = sha256_file(audit_chain_path)
    seal_now = sha256_file(audit_seal_path)
    outcome = run_verify(audit_chain_path, audit_seal_path, hmac_key_env=hmac_key_env, job_id=job_id)
    return {
        "audit_chain_sha256_matches_baseline": chain_now == expected_chain_sha256,
        "audit_seal_sha256_matches_baseline": seal_now == expected_seal_sha256,
        "verifier_passes_after_restore": not outcome["raised"],
        "verifier_error_class": outcome["error_class"],
        "verifier_error_message": outcome["error_message"],
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Verify that single-bit tampering of audit_chain.json or audit_chain.seal.json is detected by verify_audit_bundle, then restore the bundle to its baseline."
    )
    ap.add_argument("--audit-chain", required=True)
    ap.add_argument("--audit-seal", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--hmac-key-env", default="", help="Optional env var for HMAC-SHA256 audit seal verification.")
    ap.add_argument("--output", default="")
    ap.add_argument("--allow-failures", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    audit_chain_path = Path(args.audit_chain).resolve()
    audit_seal_path = Path(args.audit_seal).resolve()
    if not audit_chain_path.is_file():
        raise SystemExit(f"[ERROR] audit chain not found: {audit_chain_path}")
    if not audit_seal_path.is_file():
        raise SystemExit(f"[ERROR] audit seal not found: {audit_seal_path}")

    baseline_chain_sha = sha256_file(audit_chain_path)
    baseline_seal_sha = sha256_file(audit_seal_path)

    baseline_outcome = run_verify(
        audit_chain_path,
        audit_seal_path,
        hmac_key_env=args.hmac_key_env,
        job_id=args.job_id,
    )
    if baseline_outcome["raised"]:
        report = {
            "schema": SCHEMA_ID,
            "generated_at_utc": utc_now_iso(),
            "status": "fail",
            "reason": "baseline_verifier_failed",
            "audit_chain_path": str(audit_chain_path),
            "audit_seal_path": str(audit_seal_path),
            "baseline_audit_chain_sha256": baseline_chain_sha,
            "baseline_audit_seal_sha256": baseline_seal_sha,
            "baseline_error_class": baseline_outcome["error_class"],
            "baseline_error_message": baseline_outcome["error_message"],
            "scenarios": [],
            "summary": {"total": 0, "detected": 0, "missed": 0},
            "post_restore_check": None,
        }
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0 if args.allow_failures else 1

    scenarios = build_scenarios(audit_chain_path, audit_seal_path)
    executed = execute_scenarios(
        audit_chain_path=audit_chain_path,
        audit_seal_path=audit_seal_path,
        job_id=args.job_id,
        hmac_key_env=args.hmac_key_env,
        scenarios=scenarios,
    )

    post_check = post_restore_baseline_check(
        audit_chain_path,
        audit_seal_path,
        job_id=args.job_id,
        hmac_key_env=args.hmac_key_env,
        expected_chain_sha256=baseline_chain_sha,
        expected_seal_sha256=baseline_seal_sha,
    )

    detected = sum(1 for entry in executed if entry["detected"])
    missed = len(executed) - detected
    status_ok = (
        missed == 0
        and post_check["audit_chain_sha256_matches_baseline"]
        and post_check["audit_seal_sha256_matches_baseline"]
        and post_check["verifier_passes_after_restore"]
    )
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "status": "ok" if status_ok else "fail",
        "audit_chain_path": str(audit_chain_path),
        "audit_seal_path": str(audit_seal_path),
        "job_id": args.job_id,
        "hmac_key_env": args.hmac_key_env or None,
        "baseline_audit_chain_sha256": baseline_chain_sha,
        "baseline_audit_seal_sha256": baseline_seal_sha,
        "baseline_signature_verified": baseline_outcome["signature_verified"],
        "scenarios": executed,
        "summary": {
            "total": len(executed),
            "detected": detected,
            "missed": missed,
        },
        "post_restore_check": post_check,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.allow_failures:
        return 0
    return 0 if status_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
