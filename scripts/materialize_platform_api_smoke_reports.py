#!/usr/bin/env python3
import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def json_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch_json(opener: urllib.request.OpenerDirector, url: str, *, token: str | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with opener.open(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


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
    with opener.open(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def dump(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def expect_http_error(fn, *, code: int, label: str) -> dict[str, Any]:
    try:
        fn()
    except urllib.error.HTTPError as exc:
        if exc.code != code:
            raise
        return json.loads(exc.read().decode("utf-8"))
    raise SystemExit(f"{label} unexpectedly succeeded")


def materialize_query_api(tmp_dir: Path, *, port: int, request_file: Path) -> None:
    opener = json_opener()
    base = f"http://127.0.0.1:{port}"
    request_payload = json.load(request_file.open("r", encoding="utf-8"))
    request_base_dir = str(request_file.resolve().parent)

    dump(tmp_dir / "query_workflow_api_health.json", fetch_json(opener, f"{base}/healthz"))
    dump(
        tmp_dir / "query_workflow_api_dry_run.json",
        post_json(
            opener,
            f"{base}/v1/query-workflows/dry-run",
            request_payload,
            token="contract-query-workflow-api-token",
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
    dump(
        tmp_dir / "query_workflow_api_execute_disabled_error.json",
        expect_http_error(
            lambda: post_json(
                opener,
                f"{base}/v1/query-workflows/execute",
                request_payload,
                token="contract-query-workflow-api-token",
                request_base_dir=request_base_dir,
            ),
            code=403,
            label="query workflow API execute-disabled request",
        ),
    )


def materialize_metadata_api(tmp_dir: Path, *, port: int) -> None:
    opener = json_opener()
    base = f"http://127.0.0.1:{port}"
    dump(tmp_dir / "metadata_api_health.json", fetch_json(opener, f"{base}/healthz"))
    dump(tmp_dir / "metadata_api_job.json", fetch_json(opener, f"{base}/v1/jobs/contract-check", token="contract-metadata-api-token"))
    dump(
        tmp_dir / "metadata_api_jobs.json",
        fetch_json(opener, f"{base}/v1/jobs?caller=auto_demo&stage=bridge&limit=5", token="contract-metadata-api-token"),
    )
    dump(
        tmp_dir / "metadata_api_policies.json",
        fetch_json(opener, f"{base}/v1/entities/policies?limit=5", token="contract-metadata-api-token"),
    )
    dump(
        tmp_dir / "metadata_api_permissions.json",
        fetch_json(opener, f"{base}/v1/entities/caller-permissions?caller=auto_demo&limit=20", token="contract-metadata-api-token"),
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
        fetch_json(opener, f"{base}/v1/platform-health?{query}", token="contract-platform-health-api-token"),
    )
    dump(
        tmp_dir / "platform_health_api_unauth_error.json",
        expect_http_error(
            lambda: fetch_json(opener, f"{base}/v1/platform-health?{query}"),
            code=403,
            label="platform health API unauthenticated request",
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Materialize platform API smoke reports for contract smoke.")
    ap.add_argument("--tmp-dir", required=True)
    ap.add_argument("--query-port", type=int)
    ap.add_argument("--query-request-file")
    ap.add_argument("--metadata-port", type=int)
    ap.add_argument("--audit-port", type=int)
    ap.add_argument("--platform-health-port", type=int)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    tmp_dir = Path(args.tmp_dir).resolve()
    if args.query_port is not None:
        if not args.query_request_file:
            raise SystemExit("--query-request-file is required with --query-port")
        materialize_query_api(tmp_dir, port=args.query_port, request_file=Path(args.query_request_file))
    if args.metadata_port is not None:
        materialize_metadata_api(tmp_dir, port=args.metadata_port)
    if args.audit_port is not None:
        materialize_audit_query_api(tmp_dir, port=args.audit_port)
    if args.platform_health_port is not None:
        materialize_platform_health_api(tmp_dir, port=args.platform_health_port)
    if (
        args.query_port is None
        and args.metadata_port is None
        and args.audit_port is None
        and args.platform_health_port is None
    ):
        raise SystemExit("at least one of --query-port, --metadata-port, --audit-port, or --platform-health-port is required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
