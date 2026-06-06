#!/usr/bin/env python3
import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


HTTP_TIMEOUT_SEC = 15
DEFAULT_METADATA_TOKEN = "contract-metadata-api-token"
DEFAULT_PLATFORM_HEALTH_TOKEN = "contract-platform-health-api-token"
DEFAULT_QUERY_TOKEN = "contract-query-workflow-api-token"
DEFAULT_IDENTITY_MARKETING_TOKEN = "contract-identity-marketing-analyst-token"
DEFAULT_IDENTITY_AUTO_DEMO_TOKEN = "contract-identity-auto-demo-token"


def json_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch_json(opener: urllib.request.OpenerDirector, url: str, *, token: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_SEC) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        exc.body_text = exc.read().decode("utf-8", errors="replace")
        raise


def post_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    payload: dict[str, Any],
    *,
    token: str | None = None,
    request_base_dir: str | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if request_base_dir:
        request.add_header("X-Request-Base-Dir", request_base_dir)
    with opener.open(request, timeout=HTTP_TIMEOUT_SEC) as response:
        return json.loads(response.read().decode("utf-8"))


def dump(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def expect_http_error(fn, *, code: int, label: str) -> dict[str, Any]:
    try:
        fn()
    except urllib.error.HTTPError as exc:
        if exc.code != code:
            raise
        body = getattr(exc, "body_text", None)
        if body is None:
            body = exc.read().decode("utf-8")
        return json.loads(body)
    raise SystemExit(f"{label} unexpectedly succeeded")


def fetch_json_or_die(opener: urllib.request.OpenerDirector, url: str, *, token: str | None = None, label: str) -> dict[str, Any]:
    try:
        return fetch_json(opener, url, token=token)
    except urllib.error.HTTPError as exc:
        body = getattr(exc, "body_text", None)
        if body is None:
            body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{label} failed with HTTP {exc.code}: {body}") from exc


def materialize_query_api(tmp_dir: Path, *, port: int, request_file: Path) -> None:
    opener = json_opener()
    base = f"http://127.0.0.1:{port}"
    request_payload = json.load(request_file.open("r", encoding="utf-8"))
    request_base_dir = str(request_file.resolve().parent)

    def variant(label: str) -> dict[str, Any]:
        payload = dict(request_payload)
        payload["job_id"] = f"{request_payload['job_id']}_{label}"
        payload["out_base"] = str(tmp_dir / f"query_workflow_api_{label}_out")
        return payload

    dry_run_payload = variant("dry_run")
    dry_run_out_base = str(Path(request_base_dir, str(dry_run_payload["out_base"])).resolve())

    dump(tmp_dir / "query_workflow_api_health.json", fetch_json(opener, f"{base}/healthz"))
    dump(
        tmp_dir / "query_workflow_api_dry_run.json",
        post_json(
            opener,
            f"{base}/v1/query-workflows/dry-run",
            dry_run_payload,
            token=DEFAULT_QUERY_TOKEN,
            request_base_dir=request_base_dir,
        ),
    )
    dump(
        tmp_dir / "query_workflow_api_unauth_error.json",
        expect_http_error(
            lambda: post_json(
                opener,
                f"{base}/v1/query-workflows/dry-run",
                request_payload,
                request_base_dir=request_base_dir,
            ),
            code=403,
            label="query workflow API unauthenticated dry-run",
        ),
    )
    execute_disabled_payload = variant("execute_disabled")
    dump(
        tmp_dir / "query_workflow_api_execute_disabled_error.json",
        expect_http_error(
            lambda: post_json(
                opener,
                f"{base}/v1/query-workflows/execute",
                execute_disabled_payload,
                token=DEFAULT_QUERY_TOKEN,
                request_base_dir=request_base_dir,
            ),
            code=403,
            label="query workflow API execute-disabled request",
        ),
    )
    privacy_budget_missing_config_payload = variant("privacy_budget_missing_config")
    privacy_budget_missing_config_payload["privacy_budget_required"] = True
    privacy_budget_missing_config_payload.pop("privacy_budget_config", None)
    privacy_budget_missing_config_payload.pop("privacy_budget_ledger", None)
    dump(
        tmp_dir / "query_workflow_api_privacy_budget_missing_config_error.json",
        expect_http_error(
            lambda: post_json(
                opener,
                f"{base}/v1/query-workflows/dry-run",
                privacy_budget_missing_config_payload,
                token=DEFAULT_QUERY_TOKEN,
                request_base_dir=request_base_dir,
            ),
            code=400,
            label="query workflow API privacy-budget missing-config dry-run",
        ),
    )
    dump(
        tmp_dir / "query_workflow_api_status.json",
        fetch_json(
            opener,
            f"{base}/v1/query-workflows/status?{urllib.parse.urlencode([('out_base', dry_run_out_base), ('job_id', str(dry_run_payload['job_id']))])}",
            token=DEFAULT_QUERY_TOKEN,
        ),
    )


def materialize_query_execute_api(tmp_dir: Path, *, port: int, request_file: Path) -> None:
    opener = json_opener()
    base = f"http://127.0.0.1:{port}"
    request_payload = json.load(request_file.open("r", encoding="utf-8"))
    request_base_dir = str(request_file.resolve().parent)

    invalid_payload = dict(request_payload)
    invalid_payload.pop("query_type", None)
    dump(
        tmp_dir / "query_workflow_api_execute_validation_error.json",
        expect_http_error(
            lambda: post_json(
                opener,
                f"{base}/v1/query-workflows/execute",
                invalid_payload,
                token=DEFAULT_QUERY_TOKEN,
                request_base_dir=request_base_dir,
            ),
            code=400,
            label="query workflow API execute validation request",
        ),
    )

    run_failed_payload = dict(request_payload)
    run_failed_payload["job_id"] = "contract-query-workflow-execute-run-failed"
    run_failed_payload["out_base"] = str(tmp_dir / "query_workflow_execute_fail_out")
    run_failed_payload["token_scope"] = "contract-query-execute-run-failed"
    run_failed_payload["server_source"] = "../missing_execute_server_records.jsonl"
    run_failed_request_file = tmp_dir / "query_requests" / "cross_party_match_execute_run_failed.json"
    dump(run_failed_request_file, run_failed_payload)
    run_failed_out_base = str(Path(request_base_dir, str(run_failed_payload["out_base"])).resolve())

    client_run_failed_payload = dict(run_failed_payload)
    client_run_failed_payload["job_id"] = "contract-query-workflow-execute-run-failed-client"
    client_run_failed_payload["out_base"] = str(tmp_dir / "query_workflow_execute_fail_client_out")
    client_run_failed_payload["token_scope"] = "contract-query-execute-run-failed-client"
    client_run_failed_request_file = tmp_dir / "query_requests" / "cross_party_match_execute_run_failed_client.json"
    dump(client_run_failed_request_file, client_run_failed_payload)

    dump(
        tmp_dir / "query_workflow_api_execute_run_failed.json",
        expect_http_error(
            lambda: post_json(
                opener,
                f"{base}/v1/query-workflows/execute",
                run_failed_payload,
                token=DEFAULT_QUERY_TOKEN,
                request_base_dir=request_base_dir,
            ),
            code=502,
            label="query workflow API execute run-failed request",
        ),
    )
    dump(
        tmp_dir / "query_workflow_api_execute_run_failed_status.json",
        fetch_json(
            opener,
            f"{base}/v1/query-workflows/status?{urllib.parse.urlencode([('out_base', run_failed_out_base), ('job_id', str(run_failed_payload['job_id']))])}",
            token=DEFAULT_QUERY_TOKEN,
        ),
    )


def materialize_metadata_api(tmp_dir: Path, *, port: int) -> None:
    opener = json_opener()
    base = f"http://127.0.0.1:{port}"
    dump(tmp_dir / "metadata_api_health.json", fetch_json(opener, f"{base}/healthz"))
    dump(tmp_dir / "metadata_api_job.json", fetch_json(opener, f"{base}/v1/jobs/contract-check", token=DEFAULT_METADATA_TOKEN))
    dump(
        tmp_dir / "metadata_api_jobs.json",
        fetch_json(opener, f"{base}/v1/jobs?caller=auto_demo&stage=bridge&limit=5", token=DEFAULT_METADATA_TOKEN),
    )
    dump(
        tmp_dir / "metadata_api_policies.json",
        fetch_json(opener, f"{base}/v1/entities/policies?limit=5", token=DEFAULT_METADATA_TOKEN),
    )
    dump(
        tmp_dir / "metadata_api_permissions.json",
        fetch_json(opener, f"{base}/v1/entities/caller-permissions?caller=auto_demo&limit=20", token=DEFAULT_METADATA_TOKEN),
    )
    dump(
        tmp_dir / "metadata_api_permissions_page.json",
        fetch_json(
            opener,
            f"{base}/v1/entities/caller-permissions?caller=auto_demo&limit=2&offset=2",
            token=DEFAULT_METADATA_TOKEN,
        ),
    )
    dump(
        tmp_dir / "metadata_api_unauth_error.json",
        expect_http_error(
            lambda: fetch_json(opener, f"{base}/v1/jobs/contract-check"),
            code=403,
            label="metadata API unauthenticated job request",
        ),
    )


def materialize_audit_query_api(tmp_dir: Path, *, port: int) -> None:
    opener = json_opener()
    base = f"http://127.0.0.1:{port}"
    dump(tmp_dir / "audit_query_api_health.json", fetch_json(opener, f"{base}/healthz"))
    dump(
        tmp_dir / "audit_query_api_public_report.json",
        fetch_json(opener, f"{base}/v1/public-report", token="contract-audit-query-api-token"),
    )
    dump(
        tmp_dir / "audit_query_api_audit_chain.json",
        fetch_json(opener, f"{base}/v1/audit-chain", token="contract-audit-query-api-token"),
    )
    dump(
        tmp_dir / "audit_query_api_observability.json",
        fetch_json(opener, f"{base}/v1/observability", token="contract-audit-query-api-token"),
    )
    dump(
        tmp_dir / "audit_query_api_catalog_lineage.json",
        fetch_json(opener, f"{base}/v1/catalog-lineage", token="contract-audit-query-api-token"),
    )
    dump(
        tmp_dir / "audit_query_api_unauth_error.json",
        expect_http_error(
            lambda: fetch_json(opener, f"{base}/v1/public-report"),
            code=403,
            label="audit query API unauthenticated public report request",
        ),
    )
    dump(
        tmp_dir / "audit_query_api_bad_query_error.json",
        expect_http_error(
            lambda: fetch_json(opener, f"{base}/v1/catalog-lineage?include_paths=maybe", token="contract-audit-query-api-token"),
            code=400,
            label="audit query API invalid include_paths request",
        ),
    )


def materialize_platform_health_api(tmp_dir: Path, *, port: int) -> None:
    opener = json_opener()
    base = f"http://127.0.0.1:{port}"
    query = urllib.parse.urlencode(
        [
            ("out_base", str(tmp_dir)),
            ("metadata_db", str(tmp_dir / "platform_metadata.db")),
        ]
    )
    dump(tmp_dir / "platform_health_api_health.json", fetch_json(opener, f"{base}/healthz"))
    dump(
        tmp_dir / "platform_health_api_report.json",
        fetch_json(opener, f"{base}/v1/platform-health?{query}", token=DEFAULT_PLATFORM_HEALTH_TOKEN),
    )
    dump(
        tmp_dir / "platform_health_api_unauth_error.json",
        expect_http_error(
            lambda: fetch_json(opener, f"{base}/v1/platform-health?{query}"),
            code=403,
            label="platform health API unauthenticated request",
        ),
    )


def materialize_identity_metadata_api(tmp_dir: Path, *, port: int) -> None:
    opener = json_opener()
    base = f"http://127.0.0.1:{port}"
    dump(
        tmp_dir / "metadata_api_identity.json",
        fetch_json(opener, f"{base}/v1/identity", token=DEFAULT_IDENTITY_AUTO_DEMO_TOKEN),
    )
    dump(
        tmp_dir / "metadata_api_identity_jobs.json",
        fetch_json(opener, f"{base}/v1/jobs?caller=auto_demo&stage=bridge&limit=5", token=DEFAULT_IDENTITY_AUTO_DEMO_TOKEN),
    )
    dump(
        tmp_dir / "metadata_api_identity_job.json",
        fetch_json(opener, f"{base}/v1/jobs/contract-check", token=DEFAULT_IDENTITY_AUTO_DEMO_TOKEN),
    )
    dump(
        tmp_dir / "metadata_api_identity_permissions.json",
        fetch_json(opener, f"{base}/v1/entities/caller-permissions?caller=auto_demo&limit=20", token=DEFAULT_IDENTITY_AUTO_DEMO_TOKEN),
    )
    dump(
        tmp_dir / "metadata_api_identity_policy_bindings.json",
        fetch_json(opener, f"{base}/v1/entities/policy-bindings?caller=auto_demo&limit=20", token=DEFAULT_IDENTITY_AUTO_DEMO_TOKEN),
    )
    dump(
        tmp_dir / "metadata_api_identity_forbidden_policies.json",
        expect_http_error(
            lambda: fetch_json(opener, f"{base}/v1/entities/policies?limit=5", token=DEFAULT_IDENTITY_AUTO_DEMO_TOKEN),
            code=403,
            label="metadata API identity policies request",
        ),
    )


def materialize_identity_query_api(tmp_dir: Path, *, port: int, request_file: Path) -> None:
    opener = json_opener()
    base = f"http://127.0.0.1:{port}"
    request_payload = json.load(request_file.open("r", encoding="utf-8"))
    request_base_dir = str(request_file.resolve().parent)
    out_base = str(Path(request_base_dir, str(request_payload["out_base"])).resolve())
    dump(
        tmp_dir / "query_workflow_identity_dry_run.json",
        post_json(
            opener,
            f"{base}/v1/query-workflows/dry-run",
            request_payload,
            token=DEFAULT_IDENTITY_MARKETING_TOKEN,
            request_base_dir=request_base_dir,
        ),
    )
    dump(
        tmp_dir / "query_workflow_identity_execute_forbidden.json",
        expect_http_error(
            lambda: post_json(
                opener,
                f"{base}/v1/query-workflows/execute",
                request_payload,
                token=DEFAULT_IDENTITY_MARKETING_TOKEN,
                request_base_dir=request_base_dir,
            ),
            code=403,
            label="query workflow API identity execute request",
        ),
    )
    dump(
        tmp_dir / "query_workflow_identity_status.json",
        fetch_json(
            opener,
            f"{base}/v1/query-workflows/status?{urllib.parse.urlencode([('out_base', out_base), ('job_id', str(request_payload['job_id']))])}",
            token=DEFAULT_IDENTITY_MARKETING_TOKEN,
        ),
    )
    recovery_payload = dict(request_payload)
    recovery_payload["job_id"] = "ecommerce-query-workflow-recovery"
    recovery_payload["out_base"] = "../identity_query_workflow_recovery_out"
    recovery_payload["record_recovery_service_mode"] = "manual"
    recovery_payload["record_recovery_service_id"] = "orders-recovery"
    recovery_payload["record_recovery_endpoint_url"] = "http://127.0.0.1:9999"
    dump(
        tmp_dir / "query_workflow_identity_recovery_dry_run.json",
        post_json(
            opener,
            f"{base}/v1/query-workflows/dry-run",
            recovery_payload,
            token=DEFAULT_IDENTITY_MARKETING_TOKEN,
            request_base_dir=request_base_dir,
        ),
    )
    recovery_spoof_payload = dict(recovery_payload)
    recovery_spoof_payload["job_id"] = "ecommerce-query-workflow-recovery-spoof"
    recovery_spoof_payload["out_base"] = "../identity_query_workflow_recovery_spoof_out"
    recovery_spoof_payload["record_recovery_service_id"] = "forbidden-recovery-service"
    dump(
        tmp_dir / "query_workflow_identity_recovery_spoof_forbidden.json",
        expect_http_error(
            lambda: post_json(
                opener,
                f"{base}/v1/query-workflows/dry-run",
                recovery_spoof_payload,
                token=DEFAULT_IDENTITY_MARKETING_TOKEN,
                request_base_dir=request_base_dir,
            ),
            code=403,
            label="query workflow API identity recovery scope spoof request",
        ),
    )


def materialize_identity_audit_query_api(tmp_dir: Path, *, port: int) -> None:
    opener = json_opener()
    base = f"http://127.0.0.1:{port}"
    dump(
        tmp_dir / "audit_query_api_identity_public_report.json",
        fetch_json_or_die(opener, f"{base}/v1/public-report", token=DEFAULT_IDENTITY_AUTO_DEMO_TOKEN, label="identity audit public-report"),
    )
    dump(
        tmp_dir / "audit_query_api_identity_audit_chain.json",
        fetch_json_or_die(opener, f"{base}/v1/audit-chain", token=DEFAULT_IDENTITY_AUTO_DEMO_TOKEN, label="identity audit-chain"),
    )
    dump(
        tmp_dir / "audit_query_api_identity_observability.json",
        fetch_json_or_die(opener, f"{base}/v1/observability", token=DEFAULT_IDENTITY_AUTO_DEMO_TOKEN, label="identity audit observability"),
    )
    dump(
        tmp_dir / "audit_query_api_identity_catalog_lineage.json",
        fetch_json_or_die(opener, f"{base}/v1/catalog-lineage", token=DEFAULT_IDENTITY_AUTO_DEMO_TOKEN, label="identity audit catalog-lineage"),
    )
    dump(
        tmp_dir / "audit_query_api_identity_include_paths_forbidden.json",
        expect_http_error(
            lambda: fetch_json(
                opener,
                f"{base}/v1/catalog-lineage?include_paths=true",
                token=DEFAULT_IDENTITY_AUTO_DEMO_TOKEN,
            ),
            code=403,
            label="audit query API identity include-paths request",
        ),
    )


def materialize_identity_platform_health_api(tmp_dir: Path, *, port: int) -> None:
    opener = json_opener()
    base = f"http://127.0.0.1:{port}"
    dump(
        tmp_dir / "platform_health_api_identity_forbidden.json",
        expect_http_error(
            lambda: fetch_json(opener, f"{base}/v1/platform-health", token=DEFAULT_IDENTITY_MARKETING_TOKEN),
            code=403,
            label="platform health API identity request",
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Materialize platform API smoke reports for contract smoke.")
    ap.add_argument("--tmp-dir", required=True)
    ap.add_argument("--query-token", default=DEFAULT_QUERY_TOKEN)
    ap.add_argument("--metadata-token", default=DEFAULT_METADATA_TOKEN)
    ap.add_argument("--platform-health-token", default=DEFAULT_PLATFORM_HEALTH_TOKEN)
    ap.add_argument("--identity-marketing-token", default=DEFAULT_IDENTITY_MARKETING_TOKEN)
    ap.add_argument("--identity-auto-demo-token", default=DEFAULT_IDENTITY_AUTO_DEMO_TOKEN)
    ap.add_argument("--query-port", type=int)
    ap.add_argument("--query-request-file")
    ap.add_argument("--query-execute-port", type=int)
    ap.add_argument("--query-execute-request-file")
    ap.add_argument("--metadata-port", type=int)
    ap.add_argument("--audit-port", type=int)
    ap.add_argument("--platform-health-port", type=int)
    ap.add_argument("--identity-metadata-port", type=int)
    ap.add_argument("--identity-query-port", type=int)
    ap.add_argument("--identity-query-request-file")
    ap.add_argument("--identity-audit-port", type=int)
    ap.add_argument("--identity-platform-health-port", type=int)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    tmp_dir = Path(args.tmp_dir).resolve()
    global DEFAULT_QUERY_TOKEN, DEFAULT_METADATA_TOKEN, DEFAULT_PLATFORM_HEALTH_TOKEN, DEFAULT_IDENTITY_MARKETING_TOKEN, DEFAULT_IDENTITY_AUTO_DEMO_TOKEN
    DEFAULT_QUERY_TOKEN = args.query_token
    DEFAULT_METADATA_TOKEN = args.metadata_token
    DEFAULT_PLATFORM_HEALTH_TOKEN = args.platform_health_token
    DEFAULT_IDENTITY_MARKETING_TOKEN = args.identity_marketing_token
    DEFAULT_IDENTITY_AUTO_DEMO_TOKEN = args.identity_auto_demo_token
    if args.query_port is not None:
        if not args.query_request_file:
            raise SystemExit("--query-request-file is required with --query-port")
        materialize_query_api(tmp_dir, port=args.query_port, request_file=Path(args.query_request_file))
    if args.query_execute_port is not None:
        if not args.query_execute_request_file:
            raise SystemExit("--query-execute-request-file is required with --query-execute-port")
        materialize_query_execute_api(tmp_dir, port=args.query_execute_port, request_file=Path(args.query_execute_request_file))
    if args.metadata_port is not None:
        materialize_metadata_api(tmp_dir, port=args.metadata_port)
    if args.audit_port is not None:
        materialize_audit_query_api(tmp_dir, port=args.audit_port)
    if args.platform_health_port is not None:
        materialize_platform_health_api(tmp_dir, port=args.platform_health_port)
    if args.identity_metadata_port is not None:
        materialize_identity_metadata_api(tmp_dir, port=args.identity_metadata_port)
    if args.identity_query_port is not None:
        if not args.identity_query_request_file:
            raise SystemExit("--identity-query-request-file is required with --identity-query-port")
        materialize_identity_query_api(tmp_dir, port=args.identity_query_port, request_file=Path(args.identity_query_request_file))
    if args.identity_audit_port is not None:
        materialize_identity_audit_query_api(tmp_dir, port=args.identity_audit_port)
    if args.identity_platform_health_port is not None:
        materialize_identity_platform_health_api(tmp_dir, port=args.identity_platform_health_port)
    if (
        args.query_port is None
        and args.query_execute_port is None
        and args.metadata_port is None
        and args.audit_port is None
        and args.platform_health_port is None
        and args.identity_metadata_port is None
        and args.identity_query_port is None
        and args.identity_audit_port is None
        and args.identity_platform_health_port is None
    ):
        raise SystemExit(
            "at least one platform API port flag is required"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
