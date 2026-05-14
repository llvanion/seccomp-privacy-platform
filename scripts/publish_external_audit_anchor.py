#!/usr/bin/env python3
"""Publish local audit-archive anchor records to an external sink.

Three sink kinds are supported:

1. ``file_ledger`` (default): append each verified anchor record as an
   ``external_audit_anchor_ledger/v1`` JSONL line to a local file.
2. ``s3_worm`` (K1-a): publish the same JSONL payload to an S3 object that is
   protected by S3 Object Lock in COMPLIANCE mode.  Default behaviour stays in
   ``planned`` status so default contract smoke does not require AWS
   credentials; passing ``--execute`` is required to actually upload.
3. ``rekor`` (K1-b): submit a ``hashedrekord`` entry per anchor record to a
   Sigstore Rekor transparency log.  The signed payload is the canonical
   bytes ``b"entry_sha256:<hex>\\n"``, signed with an operator-provided ECDSA
   private key.  Default behaviour stays in ``planned`` status so default
   contract smoke needs neither network access nor key material; passing
   ``--execute`` is required to actually POST to Rekor.

In every case the script verifies the chain (payload_sha256, entry_sha256,
chain linkage, optional HMAC signature) before touching the external sink, and
emits an ``external_audit_anchor_report/v1`` document describing the result.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hmac
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.archive_audit_bundle import (  # noqa: E402
    compute_anchor_entry_sha256,
    compute_anchor_payload_sha256,
    hmac_sha256_hex,
    load_jsonl_objects,
    utc_now_iso,
)


SCHEMA_ID = "external_audit_anchor_report/v1"

_TENANT_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
_DEFAULT_RETAIN_DAYS = 3650


def validate_tenant_segment(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("tenant_id must be a non-empty string")
    candidate = value.strip()
    if not _TENANT_PATH_SEGMENT_RE.match(candidate):
        raise ValueError(
            f"tenant_id {candidate!r} is not a valid path segment "
            "(allowed: alphanumeric plus _ . -)"
        )
    if candidate in (".", ".."):
        raise ValueError(f"tenant_id {candidate!r} is not a valid path segment")
    return candidate


def assert_path_contains_tenant_segment(path: Path, *, tenant_id: str, label: str) -> None:
    parts = path.parts
    if tenant_id not in parts:
        raise ValueError(
            f"{label} {str(path)!r} does not include tenant_id {tenant_id!r} as a path segment"
        )


def parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        raise ValueError(f"S3 sink expects s3://bucket/key URI, got: {uri}")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        raise ValueError(f"S3 URI must include both bucket and key: {uri}")
    return bucket, key


def assert_s3_key_contains_tenant_segment(key: str, *, tenant_id: str, label: str) -> None:
    parts = [segment for segment in key.split("/") if segment]
    if tenant_id not in parts:
        raise ValueError(
            f"{label} key {key!r} does not include tenant_id {tenant_id!r} as a path segment"
        )


def verify_anchor_records(
    records: list[dict[str, Any]],
    *,
    anchor_key_env: str,
    require_signature: bool,
    expected_tenant_id: str | None,
) -> list[dict[str, Any]]:
    published_records: list[dict[str, Any]] = []
    previous_entry_sha256: str | None = None
    secret = os.environ.get(anchor_key_env) if anchor_key_env else None
    if anchor_key_env and not secret:
        raise ValueError(f"external audit anchor key env {anchor_key_env} is not set")
    for line_no, record in enumerate(records, 1):
        if record.get("schema") != "audit_archive_anchor/v1":
            raise ValueError(f"anchor line {line_no} has unexpected schema: {record.get('schema')}")
        expected_payload_sha256 = compute_anchor_payload_sha256(record)
        if record.get("payload_sha256") != expected_payload_sha256:
            raise ValueError(f"anchor line {line_no} payload_sha256 mismatch")
        expected_entry_sha256 = compute_anchor_entry_sha256(
            previous_anchor_entry_sha256=previous_entry_sha256,
            payload_sha256=expected_payload_sha256,
        )
        if record.get("entry_sha256") != expected_entry_sha256:
            raise ValueError(f"anchor line {line_no} entry_sha256 mismatch")
        if record.get("previous_anchor_entry_sha256") != previous_entry_sha256:
            raise ValueError(f"anchor line {line_no} previous_anchor_entry_sha256 mismatch")
        record_tenant_raw = record.get("tenant_id")
        record_tenant = str(record_tenant_raw).strip() if isinstance(record_tenant_raw, str) and record_tenant_raw.strip() else None
        if expected_tenant_id is not None:
            if record_tenant is None:
                raise ValueError(
                    f"anchor line {line_no} has no tenant_id but --tenant-id={expected_tenant_id!r} was requested"
                )
            if record_tenant != expected_tenant_id:
                raise ValueError(
                    f"anchor line {line_no} tenant_id mismatch: expected {expected_tenant_id!r}, got {record_tenant!r}"
                )
        signature_algorithm = record.get("signature_algorithm")
        signature_verified: bool | None = None
        if signature_algorithm == "hmac-sha256":
            signature = record.get("signature")
            if not isinstance(signature, str) or not signature:
                raise ValueError(f"anchor line {line_no} missing HMAC signature")
            if secret:
                expected_signature = hmac_sha256_hex(secret, str(record.get("entry_sha256") or ""))
                if not hmac.compare_digest(signature, expected_signature):
                    raise ValueError(f"anchor line {line_no} HMAC signature mismatch")
                signature_verified = True
        elif signature_algorithm is None:
            if require_signature:
                raise ValueError(f"anchor line {line_no} is unsigned")
        else:
            raise ValueError(f"anchor line {line_no} unsupported signature algorithm: {signature_algorithm}")
        published_records.append(
            {
                "job_id": str(record.get("job_id") or ""),
                "chain_position": int(record.get("chain_position") or 0),
                "entry_sha256": str(record.get("entry_sha256") or ""),
                "payload_sha256": str(record.get("payload_sha256") or ""),
                "index_record_sha256": str(record.get("index_record_sha256") or ""),
                "signature_algorithm": signature_algorithm,
                "signature_verified": signature_verified,
                "tenant_id": record_tenant,
                "published": False,
            }
        )
        previous_entry_sha256 = str(record.get("entry_sha256") or "")
    return published_records


def render_ledger_lines(
    records: list[dict[str, Any]],
    *,
    tenant_id: str | None,
) -> list[str]:
    lines: list[str] = []
    for record in records:
        payload = {
            "schema": "external_audit_anchor_ledger/v1",
            "published_at_utc": utc_now_iso(),
            "job_id": record["job_id"],
            "chain_position": record["chain_position"],
            "entry_sha256": record["entry_sha256"],
            "payload_sha256": record["payload_sha256"],
            "index_record_sha256": record["index_record_sha256"],
            "signature_algorithm": record["signature_algorithm"],
            "tenant_id": tenant_id if tenant_id is not None else record.get("tenant_id"),
        }
        lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return lines


def append_external_ledger(
    path: Path,
    records: list[dict[str, Any]],
    *,
    tenant_id: str | None,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = render_ledger_lines(records, tenant_id=tenant_id)
    with path.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
    for record in records:
        record["published"] = True
    return len(records)


def parse_rekor_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Rekor sink expects http(s):// URL, got: {url}")
    if not parsed.netloc:
        raise ValueError(f"Rekor URL must include host: {url}")
    return url.rstrip("/")


def rekor_canonical_bytes(entry_sha256: str) -> bytes:
    return f"entry_sha256:{entry_sha256}\n".encode("utf-8")


def append_rekor_ledger(
    base_url: str,
    records: list[dict[str, Any]],
    *,
    signing_pem: str,
    timeout_sec: float,
) -> list[dict[str, Any]]:
    """Submit one ``hashedrekord`` entry per anchor record to Rekor.

    Operators must provide a PEM-encoded ECDSA-P256 private key via
    ``--rekor-signing-key-env``; the corresponding public key is derived from
    it.  Returns one metadata dict per record describing the resulting Rekor
    entry (or the failure mode if the POST failed).
    """
    import base64
    import hashlib as _hashlib
    import urllib.error
    import urllib.request

    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError as exc:  # pragma: no cover - exercised at execute time
        raise RuntimeError("cryptography is required for rekor sink; install cryptography") from exc

    try:
        private_key = serialization.load_pem_private_key(signing_pem.encode("utf-8"), password=None)
    except Exception as exc:
        raise RuntimeError(f"failed to load Rekor signing key: {exc}") from exc
    if not isinstance(private_key, ec.EllipticCurvePrivateKey):
        raise RuntimeError("Rekor signing key must be an ECDSA key (P-256 / secp256r1)")
    if not isinstance(private_key.curve, ec.SECP256R1):
        raise RuntimeError("Rekor signing key must use P-256 / secp256r1 curve")

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_pem_b64 = base64.b64encode(public_pem).decode("ascii")

    endpoint = base_url.rstrip("/") + "/api/v1/log/entries"
    entries: list[dict[str, Any]] = []
    for record in records:
        canonical = rekor_canonical_bytes(record["entry_sha256"])
        digest = _hashlib.sha256(canonical).hexdigest()
        signature = private_key.sign(canonical, ec.ECDSA(hashes.SHA256()))
        rekor_entry = {
            "kind": "hashedrekord",
            "apiVersion": "0.0.1",
            "spec": {
                "data": {"hash": {"algorithm": "sha256", "value": digest}},
                "signature": {
                    "content": base64.b64encode(signature).decode("ascii"),
                    "publicKey": {"content": public_pem_b64},
                },
            },
        }
        request_body = json.dumps(rekor_entry).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=request_body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        entry_meta: dict[str, Any] = {
            "entry_sha256": record["entry_sha256"],
            "payload_sha256": digest,
            "uuid": None,
            "log_index": None,
            "integrated_time": None,
            "status": "error",
            "details": None,
        }
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                body = response.read().decode("utf-8")
                http_status = response.getcode()
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                payload = {}
            uuid_value: str | None = None
            log_index: int | None = None
            integrated_time: int | None = None
            if isinstance(payload, dict):
                for key, entry_payload in payload.items():
                    uuid_value = key
                    if isinstance(entry_payload, dict):
                        verification = entry_payload.get("verification") or {}
                        log_index = entry_payload.get("logIndex")
                        if isinstance(verification, dict):
                            integrated_time = verification.get("integratedTime") or entry_payload.get("integratedTime")
                    break
            entry_meta["uuid"] = uuid_value
            entry_meta["log_index"] = log_index if isinstance(log_index, int) else None
            entry_meta["integrated_time"] = integrated_time if isinstance(integrated_time, int) else None
            if 200 <= http_status < 300:
                entry_meta["status"] = "uploaded"
                entry_meta["details"] = f"HTTP {http_status} uuid={uuid_value or '?'}"
                record["published"] = True
            else:
                entry_meta["status"] = "error"
                entry_meta["details"] = f"HTTP {http_status}: {body[:200]}"
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                error_body = ""
            entry_meta["status"] = "error"
            entry_meta["details"] = f"HTTP {exc.code}: {error_body[:200]}"
        except Exception as exc:
            entry_meta["status"] = "error"
            entry_meta["details"] = f"transport error: {exc}"
        entries.append(entry_meta)
    return entries


def append_s3_worm_ledger(
    bucket: str,
    key: str,
    records: list[dict[str, Any]],
    *,
    tenant_id: str | None,
    object_lock_mode: str,
    retain_until_utc: str,
) -> dict[str, Any]:
    """Append `records` to an S3 Object-Lock protected JSONL ledger.

    Returns metadata about the resulting object.  Lazy-imports boto3 so that
    callers without the dependency installed do not trip an ImportError unless
    they actually request the s3_worm execute path.
    """
    try:
        import boto3  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised at execute time
        raise RuntimeError("boto3 is required for s3_worm sink; install boto3") from exc

    client = boto3.client("s3")
    previous_etag: str | None = None
    existing_body = b""
    try:
        existing = client.get_object(Bucket=bucket, Key=key)
    except client.exceptions.NoSuchKey:  # type: ignore[attr-defined]
        existing = None
    except Exception as exc:  # pragma: no cover - boto3 surface
        raise RuntimeError(f"S3 get_object failed for s3://{bucket}/{key}: {exc}") from exc
    if existing is not None:
        previous_etag = (existing.get("ETag") or "").strip('"') or None
        body = existing.get("Body")
        if body is not None:
            existing_body = body.read()

    new_lines = render_ledger_lines(records, tenant_id=tenant_id)
    suffix = ("\n".join(new_lines) + "\n").encode("utf-8") if new_lines else b""
    body_bytes = existing_body + suffix

    put_kwargs: dict[str, Any] = {
        "Bucket": bucket,
        "Key": key,
        "Body": body_bytes,
        "ContentType": "application/x-ndjson",
        "ObjectLockMode": object_lock_mode,
        "ObjectLockRetainUntilDate": retain_until_utc,
    }
    response = client.put_object(**put_kwargs)
    for record in records:
        record["published"] = True
    return {
        "etag": (response.get("ETag") or "").strip('"') or None,
        "version_id": response.get("VersionId"),
        "previous_object_etag": previous_etag,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish local audit archive anchor records to an external anchor sink.")
    ap.add_argument("--anchor-file", required=True)
    ap.add_argument("--external-ledger", required=True)
    ap.add_argument("--output", default="")
    ap.add_argument("--anchor-key-env", default="")
    ap.add_argument("--require-signature", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--assert-ok", action="store_true")
    ap.add_argument(
        "--tenant-id",
        default="",
        help=(
            "Optional tenant scope. When set, --anchor-file must live under a directory "
            "named <tenant-id>, --external-ledger must include <tenant-id> as a path segment, "
            "and every anchor record must carry tenant_id=<tenant-id>."
        ),
    )
    ap.add_argument(
        "--sink-kind",
        choices=("file_ledger", "s3_worm", "rekor"),
        default="file_ledger",
        help=(
            "External sink kind. file_ledger appends to a local JSONL; s3_worm uploads to "
            "S3 with Object Lock; rekor submits one hashedrekord entry per anchor record."
        ),
    )
    ap.add_argument(
        "--object-lock-mode",
        choices=("COMPLIANCE", "GOVERNANCE"),
        default="COMPLIANCE",
        help="S3 Object Lock retention mode (s3_worm sink only).",
    )
    ap.add_argument(
        "--retain-days",
        type=int,
        default=_DEFAULT_RETAIN_DAYS,
        help="S3 Object Lock retain-until horizon in days (s3_worm sink only).",
    )
    ap.add_argument(
        "--rekor-signing-key-env",
        default="",
        help="Env var holding the PEM-encoded ECDSA P-256 private key used to sign hashedrekord entries (rekor sink only, --execute path).",
    )
    ap.add_argument(
        "--rekor-timeout-sec",
        type=float,
        default=10.0,
        help="HTTP timeout (seconds) for Rekor POSTs (rekor sink only).",
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Actually publish to the external sink (s3_worm uploads to S3, rekor POSTs to "
            "the transparency log). Without --execute, both paths stay in planned status."
        ),
    )
    ap.add_argument(
        "--production-mode",
        action="store_true",
        help=(
            "S6 production gate: file_ledger sinks are rejected as the sole anchor target, "
            "--execute must be set, and s3_worm/rekor sinks must finish in 'uploaded' status. "
            "Adds production_mode/production_findings to the report and forces summary.status=fail "
            "on any production constraint violation."
        ),
    )
    args = ap.parse_args()

    tenant_id: str | None = None
    if args.tenant_id:
        tenant_id = validate_tenant_segment(args.tenant_id)

    anchor_path = Path(args.anchor_file).resolve()
    if tenant_id is not None:
        assert_path_contains_tenant_segment(anchor_path, tenant_id=tenant_id, label="--anchor-file")

    if args.retain_days < 1:
        raise ValueError("--retain-days must be a positive integer")

    ledger_path: Path | None = None
    s3_bucket: str | None = None
    s3_key: str | None = None
    rekor_url: str | None = None
    sink_path_display = ""
    if args.sink_kind == "file_ledger":
        ledger_path = Path(args.external_ledger).resolve()
        sink_path_display = str(ledger_path)
        if tenant_id is not None:
            assert_path_contains_tenant_segment(ledger_path, tenant_id=tenant_id, label="--external-ledger")
    elif args.sink_kind == "s3_worm":
        s3_bucket, s3_key = parse_s3_uri(args.external_ledger)
        sink_path_display = f"s3://{s3_bucket}/{s3_key}"
        if tenant_id is not None:
            assert_s3_key_contains_tenant_segment(s3_key, tenant_id=tenant_id, label="--external-ledger")
    else:  # rekor
        rekor_url = parse_rekor_url(args.external_ledger)
        sink_path_display = rekor_url

    records = verify_anchor_records(
        load_jsonl_objects(str(anchor_path)),
        anchor_key_env=args.anchor_key_env,
        require_signature=args.require_signature,
        expected_tenant_id=tenant_id,
    )

    published_count = 0
    sink_block: dict[str, Any] = {
        "kind": args.sink_kind,
        "path": sink_path_display,
        "tenant_id": tenant_id,
    }
    production_findings: list[dict[str, Any]] = []
    if args.production_mode:
        if args.sink_kind == "file_ledger":
            production_findings.append(
                {
                    "kind": "production_file_ledger_not_external",
                    "message": (
                        "production-mode rejects file_ledger as the sole anchor sink; "
                        "use --sink-kind s3_worm or --sink-kind rekor for external immutability"
                    ),
                    "ref": sink_path_display,
                }
            )
        if args.dry_run:
            production_findings.append(
                {
                    "kind": "production_dry_run_not_allowed",
                    "message": "production-mode rejects --dry-run; the anchor must actually publish",
                    "ref": None,
                }
            )
        if not args.execute and args.sink_kind in ("s3_worm", "rekor"):
            production_findings.append(
                {
                    "kind": "production_execute_required",
                    "message": (
                        f"production-mode requires --execute for sink_kind={args.sink_kind}; "
                        "planned status cannot satisfy production gate"
                    ),
                    "ref": None,
                }
            )

    if args.sink_kind == "file_ledger":
        if not args.production_mode and not args.dry_run and records and ledger_path is not None:
            published_count = append_external_ledger(ledger_path, records, tenant_id=tenant_id)
    elif args.sink_kind == "s3_worm":
        retain_until_dt = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=args.retain_days)
        retain_until_utc = retain_until_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        s3_block: dict[str, Any] = {
            "bucket": s3_bucket,
            "key": s3_key,
            "object_lock_mode": args.object_lock_mode,
            "retain_until_utc": retain_until_utc,
            "retain_days": args.retain_days,
            "executed": False,
            "status": "planned",
            "details": "S3 Object Lock upload skipped: pass --execute to actually upload",
            "etag": None,
            "version_id": None,
            "previous_object_etag": None,
        }
        if args.dry_run:
            s3_block["status"] = "skipped"
            s3_block["details"] = "skipped because --dry-run was set"
        elif args.execute and records and s3_bucket and s3_key:
            try:
                upload_meta = append_s3_worm_ledger(
                    s3_bucket,
                    s3_key,
                    records,
                    tenant_id=tenant_id,
                    object_lock_mode=args.object_lock_mode,
                    retain_until_utc=retain_until_utc,
                )
                s3_block["executed"] = True
                s3_block["status"] = "uploaded"
                s3_block["details"] = (
                    f"uploaded to s3://{s3_bucket}/{s3_key} with ObjectLockMode={args.object_lock_mode} "
                    f"retain_until={retain_until_utc}"
                )
                s3_block["etag"] = upload_meta.get("etag")
                s3_block["version_id"] = upload_meta.get("version_id")
                s3_block["previous_object_etag"] = upload_meta.get("previous_object_etag")
                published_count = len(records)
            except Exception as exc:
                s3_block["status"] = "error"
                s3_block["details"] = f"S3 upload failed: {exc}"
        sink_block["s3_object_lock"] = s3_block
    else:  # rekor
        rekor_block: dict[str, Any] = {
            "endpoint_url": rekor_url,
            "endpoint_path": "/api/v1/log/entries",
            "kind_version": "hashedrekord/0.0.1",
            "signature_algorithm": "ecdsa-p256-sha256",
            "executed": False,
            "status": "planned",
            "details": (
                "Rekor submission skipped: pass --execute (and --rekor-signing-key-env "
                "<env>) to actually POST to the transparency log"
            ),
            "entries": [],
            "submitted_count": 0,
            "uploaded_count": 0,
        }
        if args.dry_run:
            rekor_block["status"] = "skipped"
            rekor_block["details"] = "skipped because --dry-run was set"
        elif args.execute and records and rekor_url is not None:
            signing_pem = os.environ.get(args.rekor_signing_key_env) if args.rekor_signing_key_env else None
            if not signing_pem:
                rekor_block["status"] = "error"
                rekor_block["details"] = (
                    "rekor signing key env not set; pass --rekor-signing-key-env <env> "
                    "with a PEM-encoded ECDSA P-256 private key"
                )
            else:
                try:
                    entries = append_rekor_ledger(
                        rekor_url,
                        records,
                        signing_pem=signing_pem,
                        timeout_sec=args.rekor_timeout_sec,
                    )
                    rekor_block["executed"] = True
                    rekor_block["entries"] = entries
                    rekor_block["submitted_count"] = len(entries)
                    uploaded = sum(1 for entry in entries if entry["status"] == "uploaded")
                    rekor_block["uploaded_count"] = uploaded
                    if uploaded == len(entries) and entries:
                        rekor_block["status"] = "uploaded"
                        rekor_block["details"] = (
                            f"submitted {uploaded} hashedrekord entries to {rekor_url}"
                        )
                    elif uploaded == 0:
                        rekor_block["status"] = "error"
                        rekor_block["details"] = "no Rekor entries succeeded"
                    else:
                        rekor_block["status"] = "partial"
                        rekor_block["details"] = (
                            f"{uploaded}/{len(entries)} hashedrekord entries succeeded"
                        )
                    published_count = uploaded
                except Exception as exc:
                    rekor_block["status"] = "error"
                    rekor_block["details"] = f"Rekor submission failed: {exc}"
        sink_block["rekor_transparency_log"] = rekor_block

    status = "ok" if records else "fail"
    if args.sink_kind == "s3_worm":
        s3_status = sink_block.get("s3_object_lock", {}).get("status")
        if s3_status == "error":
            status = "fail"
    elif args.sink_kind == "rekor":
        rekor_status = sink_block.get("rekor_transparency_log", {}).get("status")
        if rekor_status == "error":
            status = "fail"

    if args.production_mode:
        if args.sink_kind == "s3_worm":
            s3_status = sink_block.get("s3_object_lock", {}).get("status")
            if s3_status != "uploaded":
                production_findings.append(
                    {
                        "kind": "production_external_anchor_not_uploaded",
                        "message": (
                            f"production-mode requires s3_object_lock.status='uploaded'; got "
                            f"status={s3_status!r}"
                        ),
                        "ref": sink_path_display,
                    }
                )
        elif args.sink_kind == "rekor":
            rekor_status = sink_block.get("rekor_transparency_log", {}).get("status")
            if rekor_status != "uploaded":
                production_findings.append(
                    {
                        "kind": "production_external_anchor_not_uploaded",
                        "message": (
                            f"production-mode requires rekor_transparency_log.status='uploaded'; got "
                            f"status={rekor_status!r}"
                        ),
                        "ref": sink_path_display,
                    }
                )
        if production_findings:
            status = "fail"

    summary = {
        "status": status,
        "anchor_record_count": len(records),
        "published_count": published_count,
        "verified_chain": bool(records),
        "signed_count": sum(1 for record in records if record["signature_algorithm"] == "hmac-sha256"),
        "last_entry_sha256": records[-1]["entry_sha256"] if records else None,
        "tenant_id": tenant_id,
    }
    report: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now_iso(),
        "source_anchor_file": str(anchor_path),
        "tenant_id": tenant_id,
        "external_sink": sink_block,
        "mode": "dry_run" if args.dry_run else "publish",
        "summary": summary,
        "records": records,
    }
    if args.production_mode:
        report["production_mode"] = True
        report["production_findings"] = production_findings
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.assert_ok and status != "ok":
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        raise SystemExit(f"[ERROR] {e}") from e
