#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from source_attestation_lib import (
    SOURCE_ATTESTATION_APPROVED_STATUSES,
    SOURCE_ATTESTATION_MODES,
    SOURCE_ATTESTATION_SCHEMA,
    SOURCE_ATTESTATION_SIGNOFF_STATUSES,
    SOURCE_EXPORT_MANIFEST_SCHEMA,
    attach_ed25519_signature,
    combined_hash,
    file_descriptor,
    same_identity,
    sha256_file,
    utc_now_iso,
    validate_schema,
    write_json,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Build typed source export and source attestation artifacts.")
    ap.add_argument("--output-attestation", required=True)
    ap.add_argument("--output-export-manifest", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument("--caller", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--purpose", required=True)
    ap.add_argument("--source-system", required=True)
    ap.add_argument("--approval-id", required=True)
    ap.add_argument("--operator-identity", required=True)
    ap.add_argument("--reviewer-identity", default="")
    ap.add_argument(
        "--signoff-status",
        required=True,
        choices=sorted(SOURCE_ATTESTATION_SIGNOFF_STATUSES),
    )
    ap.add_argument(
        "--attestation-mode",
        required=True,
        choices=sorted(SOURCE_ATTESTATION_MODES),
    )
    ap.add_argument("--server-source", required=True)
    ap.add_argument("--client-source", required=True)
    ap.add_argument("--server-bridge-input", required=True)
    ap.add_argument("--client-bridge-input", required=True)
    ap.add_argument("--input-commitment", required=True)
    ap.add_argument("--created-at-utc", default="")
    ap.add_argument("--operator-signed-at-utc", default="")
    ap.add_argument("--reviewer-signed-at-utc", default="")
    ap.add_argument("--signing-key-path", default="")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    created_at = args.created_at_utc or utc_now_iso()

    source_files = [
        file_descriptor(label="server_source", path=Path(args.server_source)),
        file_descriptor(label="client_source", path=Path(args.client_source)),
    ]
    bridge_input_files = [
        file_descriptor(label="server_bridge_input", path=Path(args.server_bridge_input)),
        file_descriptor(label="client_bridge_input", path=Path(args.client_bridge_input)),
    ]
    source_snapshot_sha256 = combined_hash(source_files)
    bridge_input_sha256 = combined_hash(bridge_input_files)
    export_manifest = {
        "schema": SOURCE_EXPORT_MANIFEST_SCHEMA,
        "generated_at_utc": created_at,
        "job_id": args.job_id,
        "caller": args.caller,
        "tenant": args.tenant,
        "dataset": args.dataset,
        "purpose": args.purpose,
        "source_system": args.source_system,
        "source_snapshot_sha256": source_snapshot_sha256,
        "bridge_input_sha256": bridge_input_sha256,
        "source_files": source_files,
        "bridge_input_files": bridge_input_files,
    }
    validate_schema(export_manifest, repo_root=REPO_ROOT, schema_filename="source_export_manifest.schema.json")

    export_manifest_path = Path(args.output_export_manifest).resolve()
    write_json(export_manifest_path, export_manifest)
    export_manifest_sha256 = sha256_file(export_manifest_path)

    if args.signoff_status == "approved_dual" and not args.reviewer_identity.strip():
        raise SystemExit("[ERROR] signoff_status=approved_dual requires --reviewer-identity")
    if args.signoff_status == "approved_dual" and same_identity(args.operator_identity, args.reviewer_identity):
        raise SystemExit("[ERROR] signoff_status=approved_dual requires reviewer identity distinct from operator identity")

    operator_signed_at = args.operator_signed_at_utc or (created_at if args.signoff_status in SOURCE_ATTESTATION_APPROVED_STATUSES else None)
    reviewer_signed_at = args.reviewer_signed_at_utc or (created_at if args.signoff_status == "approved_dual" else None)
    attestation = {
        "schema": SOURCE_ATTESTATION_SCHEMA,
        "generated_at_utc": created_at,
        "tenant": args.tenant,
        "dataset": args.dataset,
        "purpose": args.purpose,
        "job_id": args.job_id,
        "caller": args.caller,
        "source_system": args.source_system,
        "source_snapshot_sha256": source_snapshot_sha256,
        "bridge_input_sha256": bridge_input_sha256,
        "input_commitment_sha256": sha256_file(Path(args.input_commitment).resolve()),
        "sealed_export_manifest_sha256": export_manifest_sha256,
        "approval_id": args.approval_id,
        "operator_identity": args.operator_identity,
        "operator_signed_at_utc": operator_signed_at,
        "reviewer_identity": args.reviewer_identity.strip() or None,
        "reviewer_signed_at_utc": reviewer_signed_at,
        "signoff_status": args.signoff_status,
        "attestation_mode": args.attestation_mode,
        "created_at_utc": created_at,
        "signed_at_utc": None,
        "signature_algorithm": None,
        "canonicalization": None,
        "payload_sha256": None,
        "signature": None,
        "public_key_pem": None,
        "public_key_fingerprint_sha256": None,
    }
    if args.signing_key_path:
        attestation = attach_ed25519_signature(
            attestation=attestation,
            signing_key_path=Path(args.signing_key_path).resolve(),
            signed_at_utc=created_at,
        )
    validate_schema(attestation, repo_root=REPO_ROOT, schema_filename="source_attestation.schema.json")
    attestation_path = Path(args.output_attestation).resolve()
    write_json(attestation_path, attestation)
    print(
        json.dumps(
            {
            "schema": "source_attestation_build/v1",
            "attestation_path": str(attestation_path),
            "export_manifest_path": str(export_manifest_path),
            "source_snapshot_sha256": source_snapshot_sha256,
            "bridge_input_sha256": bridge_input_sha256,
            "input_commitment_sha256": attestation["input_commitment_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
