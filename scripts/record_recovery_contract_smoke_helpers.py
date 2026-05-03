#!/usr/bin/env python3
import argparse
import csv
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SSE_ROOT = REPO_ROOT / "sse"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SSE_ROOT) not in sys.path:
    sys.path.insert(0, str(SSE_ROOT))


def load_json(path: Path) -> dict:
    return json.load(path.open("r", encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def build_store(out_path: Path) -> None:
    from services.record_recovery.encrypted_record_store import build_record_store

    rows = [
        {"email": "alice@example.com", "campaign": "demo", "amount": "125"},
        {"email": "bob@example.com", "campaign": "demo", "amount": "300"},
        {"email": "carol@example.com", "campaign": "other", "amount": "50"},
    ]
    build_record_store(
        rows=rows,
        out_path=out_path,
        record_id_field="email",
        key_env="SSE_RECORD_STORE_PASSPHRASE",
    )


def validate_unix_status(status_json: Path) -> None:
    data = load_json(status_json)
    require(data.get("reachable") is True, "status check did not reach record recovery service")
    require(
        (data.get("health") or {}).get("schema") == "sse_record_recovery_health/v1",
        "status check returned unexpected health schema",
    )


def run_http_recovery(
    store_path: Path,
    out_csv: Path,
    result_json: Path,
    port: int,
    *,
    caller: str = "auto_demo",
    job_id: str = "contract-http-check",
    tenant_id: str = "demo_tenant",
    dataset_id: str = "bridge_demo_dataset",
    service_id: str = "bridge-demo-recovery",
) -> None:
    from services.record_recovery.client import request_record_recovery

    result = request_record_recovery(
        endpoint_url=f"http://127.0.0.1:{port}",
        auth_env="SSE_RECORD_RECOVERY_TOKEN",
        caller=caller,
        job_id=job_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        service_id=service_id,
        record_store_path=store_path,
        record_store_key_env="SSE_RECORD_STORE_PASSPHRASE",
        out_path=out_csv,
        out_format="csv",
        role="client",
        join_key_field="email",
        value_field="amount",
        filter_pairs=[("campaign", "demo")],
        candidate_ids={"alice@example.com", "carol@example.com"},
        min_output_rows=1,
        max_output_rows=5,
    )
    result_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_http_recovery(status_json: Path, health_json: Path, result_json: Path, out_csv: Path) -> None:
    status = load_json(status_json)
    health = load_json(health_json)
    result = load_json(result_json)
    with out_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    require(status.get("reachable") is True, "HTTP record recovery status check did not reach the service")
    require((status.get("health") or {}).get("transport") == "http", "HTTP record recovery status returned non-http transport")
    require(health.get("transport") == "http", "HTTP record recovery health returned non-http transport")
    require(result.get("output_rows") == 1, f"unexpected HTTP recovery output_rows: {result.get('output_rows')}")
    require(
        len(rows) == 1 and rows[0].get("email") == "alice@example.com" and rows[0].get("amount") == "125",
        f"unexpected HTTP recovery CSV rows: {rows}",
    )


def expect_http_deny(store_path: Path, port: int) -> None:
    from services.record_recovery.client import request_record_recovery

    try:
        request_record_recovery(
            endpoint_url=f"http://127.0.0.1:{port}",
            auth_env="SSE_RECORD_RECOVERY_TOKEN",
            caller="auto_demo",
            job_id="contract-http-check-deny",
            tenant_id="demo_tenant",
            dataset_id="bridge_demo_dataset",
            service_id="wrong-service",
            record_store_path=store_path,
            record_store_key_env="SSE_RECORD_STORE_PASSPHRASE",
            out_path=store_path.parent / "http_recovered_client_deny.csv",
            out_format="csv",
            role="client",
            join_key_field="email",
            value_field="amount",
            filter_pairs=[("campaign", "demo")],
            candidate_ids={"alice@example.com"},
            min_output_rows=1,
            max_output_rows=5,
        )
    except Exception:
        return
    raise SystemExit("unexpectedly allowed wrong-service HTTP record recovery request")


def run_http_export(store_path: Path, out_csv: Path, audit_jsonl: Path, port: int) -> None:
    from frontend.client.commands import export_bridge_records

    export_bridge_records(
        source_path="",
        out_path=str(out_csv),
        role="client",
        source_format="jsonl",
        out_format="csv",
        join_key_field="email",
        value_field="amount",
        filters=["campaign=demo"],
        caller="auto_demo",
        policy_config=str(REPO_ROOT / "sse" / "config" / "export_policy.example.json"),
        audit_log=str(audit_jsonl),
        job_id="contract-http-export",
        tenant_id="demo_tenant",
        dataset_id="bridge_demo_dataset",
        unsafe_allow_no_policy=False,
        candidate_ids={"alice@example.com", "carol@example.com"},
        record_store_path=str(store_path),
        record_store_key_env="SSE_RECORD_STORE_PASSPHRASE",
        record_recovery_socket="",
        record_recovery_endpoint_url=f"http://127.0.0.1:{port}",
        record_recovery_auth_env="SSE_RECORD_RECOVERY_TOKEN",
        record_recovery_service_id="bridge-demo-recovery",
    )


def validate_http_export(out_csv: Path, audit_jsonl: Path) -> None:
    with out_csv.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with audit_jsonl.open("r", encoding="utf-8") as handle:
        audit_records = [json.loads(line) for line in handle if line.strip()]

    require(
        len(rows) == 1 and rows[0].get("email") == "alice@example.com" and rows[0].get("amount") == "125",
        f"unexpected HTTP export CSV rows: {rows}",
    )
    require(
        len(audit_records) == 1 and audit_records[0].get("record_recovery_boundary") == "service_http",
        f"unexpected HTTP export audit records: {audit_records}",
    )


def validate_authz_db_source(health_json: Path, audit_jsonl: Path, authz_config: Path) -> None:
    health = load_json(health_json)
    with audit_jsonl.open("r", encoding="utf-8") as handle:
        audit_records = [json.loads(line) for line in handle if line.strip()]

    expected_authz_config = str(authz_config.resolve())
    require(
        health.get("authz_policy_config") == expected_authz_config,
        f"unexpected authz_policy_config in health payload: {health}",
    )
    require(audit_records, "record recovery service audit log is empty")
    require(
        audit_records[0].get("authz_policy_config") == expected_authz_config,
        f"unexpected authz_policy_config in audit payload: {audit_records}",
    )
    require(
        audit_records[0].get("decision") == "allow",
        f"unexpected authz DB recovery audit decision: {audit_records}",
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Record-recovery contract-smoke helpers.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    build = sub.add_parser("build-store")
    build.add_argument("--out-path", required=True)

    unix_status = sub.add_parser("validate-unix-status")
    unix_status.add_argument("--status-json", required=True)

    run_recovery = sub.add_parser("run-http-recovery")
    run_recovery.add_argument("--store-path", required=True)
    run_recovery.add_argument("--out-csv", required=True)
    run_recovery.add_argument("--result-json", required=True)
    run_recovery.add_argument("--port", type=int, required=True)
    run_recovery.add_argument("--caller", default="auto_demo")
    run_recovery.add_argument("--job-id", default="contract-http-check")
    run_recovery.add_argument("--tenant-id", default="demo_tenant")
    run_recovery.add_argument("--dataset-id", default="bridge_demo_dataset")
    run_recovery.add_argument("--service-id", default="bridge-demo-recovery")

    validate_recovery = sub.add_parser("validate-http-recovery")
    validate_recovery.add_argument("--status-json", required=True)
    validate_recovery.add_argument("--health-json", required=True)
    validate_recovery.add_argument("--result-json", required=True)
    validate_recovery.add_argument("--out-csv", required=True)

    deny = sub.add_parser("expect-http-deny")
    deny.add_argument("--store-path", required=True)
    deny.add_argument("--port", type=int, required=True)

    run_export = sub.add_parser("run-http-export")
    run_export.add_argument("--store-path", required=True)
    run_export.add_argument("--out-csv", required=True)
    run_export.add_argument("--audit-jsonl", required=True)
    run_export.add_argument("--port", type=int, required=True)

    validate_export = sub.add_parser("validate-http-export")
    validate_export.add_argument("--out-csv", required=True)
    validate_export.add_argument("--audit-jsonl", required=True)

    validate_authz = sub.add_parser("validate-authz-db-source")
    validate_authz.add_argument("--health-json", required=True)
    validate_authz.add_argument("--audit-jsonl", required=True)
    validate_authz.add_argument("--authz-config", required=True)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.cmd == "build-store":
        build_store(Path(args.out_path))
    elif args.cmd == "validate-unix-status":
        validate_unix_status(Path(args.status_json))
    elif args.cmd == "run-http-recovery":
        run_http_recovery(
            Path(args.store_path),
            Path(args.out_csv),
            Path(args.result_json),
            args.port,
            caller=args.caller,
            job_id=args.job_id,
            tenant_id=args.tenant_id,
            dataset_id=args.dataset_id,
            service_id=args.service_id,
        )
    elif args.cmd == "validate-http-recovery":
        validate_http_recovery(Path(args.status_json), Path(args.health_json), Path(args.result_json), Path(args.out_csv))
    elif args.cmd == "expect-http-deny":
        expect_http_deny(Path(args.store_path), args.port)
    elif args.cmd == "run-http-export":
        run_http_export(Path(args.store_path), Path(args.out_csv), Path(args.audit_jsonl), args.port)
    elif args.cmd == "validate-http-export":
        validate_http_export(Path(args.out_csv), Path(args.audit_jsonl))
    elif args.cmd == "validate-authz-db-source":
        validate_authz_db_source(
            Path(args.health_json),
            Path(args.audit_jsonl),
            Path(args.authz_config),
        )
    else:
        raise SystemExit(f"unknown command: {args.cmd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
