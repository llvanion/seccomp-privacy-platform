#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_external_kms(out_config: Path, state_path: Path, port: int) -> None:
    payload = {
        "schema": "external_kms_config/v1",
        "endpoint_url": f"http://127.0.0.1:{port}",
        "auth_token_env": "SECCOMP_EXTERNAL_KMS_TOKEN",
        "admin_auth_token_env": "SECCOMP_EXTERNAL_KMS_ADMIN_TOKEN",
        "request_timeout_sec": 5,
        "auto_start": {
            "bind_host": "127.0.0.1",
            "port": port,
            "state_file": str(state_path),
        },
    }
    write_json(out_config, payload)


def build_record_recovery_unix(out_config: Path, tmp_dir: Path) -> None:
    payload = {
        "schema": "record_recovery_service_config/v1",
        "service_id": "contract-recovery-service",
        "tenant_id": "contract-tenant",
        "dataset_id": "contract-dataset",
        "socket_path": str((tmp_dir / "record_recovery.sock").resolve()),
        "socket_mode": "600",
        "auth_token_env": "SSE_RECORD_RECOVERY_TOKEN",
        "allowed_callers": ["auto_demo"],
        "allowed_output_roots": [str(tmp_dir.resolve())],
        "allowed_record_store_roots": [str(tmp_dir.resolve())],
        "audit_log": str((tmp_dir / "record_recovery_service_runtime_audit.jsonl").resolve()),
        "lifecycle": {
            "pid_file": str((tmp_dir / "record_recovery_service.pid").resolve()),
            "ready_file": str((tmp_dir / "record_recovery_service.ready").resolve()),
            "log_file": str((tmp_dir / "record_recovery_service.log").resolve()),
        },
    }
    write_json(out_config, payload)


def build_record_recovery_http(out_config: Path, tmp_dir: Path, port: int) -> None:
    payload = {
        "schema": "record_recovery_service_config/v1",
        "transport": "http",
        "service_id": "bridge-demo-recovery",
        "tenant_id": "demo_tenant",
        "dataset_id": "bridge_demo_dataset",
        "endpoint_url": f"http://127.0.0.1:{port}",
        "http_listener": {
            "bind_host": "127.0.0.1",
            "port": port,
        },
        "auth_token_env": "SSE_RECORD_RECOVERY_TOKEN",
        "allowed_callers": ["auto_demo"],
        "allowed_output_roots": [str(tmp_dir.resolve())],
        "allowed_record_store_roots": [str(tmp_dir.resolve())],
        "audit_log": str((tmp_dir / "record_recovery_service_http_runtime_audit.jsonl").resolve()),
        "lifecycle": {
            "pid_file": str((tmp_dir / "record_recovery_service_http.pid").resolve()),
            "ready_file": str((tmp_dir / "record_recovery_service_http.ready").resolve()),
            "log_file": str((tmp_dir / "record_recovery_service_http.log").resolve()),
        },
    }
    write_json(out_config, payload)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Build runtime contract-smoke config fixtures.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    kms = sub.add_parser("external-kms")
    kms.add_argument("--out-config", required=True)
    kms.add_argument("--state-path", required=True)
    kms.add_argument("--port", type=int, required=True)

    unix_rr = sub.add_parser("record-recovery-unix")
    unix_rr.add_argument("--out-config", required=True)
    unix_rr.add_argument("--tmp-dir", required=True)

    http_rr = sub.add_parser("record-recovery-http")
    http_rr.add_argument("--out-config", required=True)
    http_rr.add_argument("--tmp-dir", required=True)
    http_rr.add_argument("--port", type=int, required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.cmd == "external-kms":
        build_external_kms(Path(args.out_config), Path(args.state_path), args.port)
    elif args.cmd == "record-recovery-unix":
        build_record_recovery_unix(Path(args.out_config), Path(args.tmp_dir))
    elif args.cmd == "record-recovery-http":
        build_record_recovery_http(Path(args.out_config), Path(args.tmp_dir), args.port)
    else:
        raise SystemExit(f"unknown command: {args.cmd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
