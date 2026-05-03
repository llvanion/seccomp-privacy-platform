#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener


DEFAULT_METADATA_BASE_URL = "http://127.0.0.1:18090"
DEFAULT_QUERY_BASE_URL = "http://127.0.0.1:18091"
DEFAULT_AUDIT_BASE_URL = "http://127.0.0.1:18092"
DEFAULT_PLATFORM_HEALTH_BASE_URL = "http://127.0.0.1:18093"
DEFAULT_METADATA_AUTH_ENV = "SECCOMP_METADATA_API_TOKEN"
DEFAULT_QUERY_AUTH_ENV = "SECCOMP_QUERY_WORKFLOW_API_TOKEN"
DEFAULT_AUDIT_AUTH_ENV = "SECCOMP_AUDIT_QUERY_API_TOKEN"
DEFAULT_PLATFORM_HEALTH_AUTH_ENV = "SECCOMP_PLATFORM_HEALTH_API_TOKEN"


def read_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"[ERROR] JSON payload must be an object: {path}")
    return payload


def write_output(payload: Any, output_file: str) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if output_file:
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def build_url(base_url: str, path: str, params: list[tuple[str, str]] | None = None) -> str:
    base = base_url.rstrip("/")
    query = urlencode(params or [])
    return f"{base}{path}" if not query else f"{base}{path}?{query}"


def parse_params(values: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for item in values:
        if "=" not in item:
            raise SystemExit(f"[ERROR] expected KEY=VALUE for --param, got: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit(f"[ERROR] parameter key cannot be empty: {item}")
        parsed.append((key, value))
    return parsed


def resolve_auth_token(env_name: str) -> str:
    if not env_name:
        return ""
    value = os.environ.get(env_name, "")
    if not value:
        raise SystemExit(f"[ERROR] environment variable {env_name} is not set")
    return value


def resolve_request_auth_token(*, auth_token_env: str, identity_token_env: str) -> str:
    if identity_token_env:
        return resolve_auth_token(identity_token_env)
    return resolve_auth_token(auth_token_env)


def request_json(
    *,
    url: str,
    method: str,
    auth_token: str = "",
    json_body: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    headers = {"Content-Type": "application/json"} if json_body is not None else {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    if extra_headers:
        headers.update(extra_headers)

    body = None
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")

    request = Request(url, data=body, headers=headers, method=method)
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw), exc.code
        except json.JSONDecodeError:
            return {"error": raw or str(exc)}, exc.code
    except URLError as exc:
        raise SystemExit(f"[ERROR] request failed: {exc}") from exc

    try:
        return json.loads(raw), 0
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[ERROR] response was not valid JSON: {exc}") from exc


def add_output_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-file", default="", help="Optional path to write the JSON response")


def add_metadata_http_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=DEFAULT_METADATA_BASE_URL)
    parser.add_argument(
        "--auth-token-env",
        default=DEFAULT_METADATA_AUTH_ENV,
        help=f"Bearer-token env var for metadata API calls (default: {DEFAULT_METADATA_AUTH_ENV})",
    )
    parser.add_argument("--identity-token-env", default="", help="Optional identity bearer-token env var; overrides --auth-token-env")


def add_query_http_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=DEFAULT_QUERY_BASE_URL)
    parser.add_argument(
        "--auth-token-env",
        default=DEFAULT_QUERY_AUTH_ENV,
        help=f"Bearer-token env var for query API calls (default: {DEFAULT_QUERY_AUTH_ENV})",
    )
    parser.add_argument("--identity-token-env", default="", help="Optional identity bearer-token env var; overrides --auth-token-env")


def add_audit_http_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=DEFAULT_AUDIT_BASE_URL)
    parser.add_argument(
        "--auth-token-env",
        default=DEFAULT_AUDIT_AUTH_ENV,
        help=f"Bearer-token env var for audit/public-report API calls (default: {DEFAULT_AUDIT_AUTH_ENV})",
    )
    parser.add_argument("--identity-token-env", default="", help="Optional identity bearer-token env var; overrides --auth-token-env")


def add_platform_health_http_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=DEFAULT_PLATFORM_HEALTH_BASE_URL)
    parser.add_argument(
        "--auth-token-env",
        default=DEFAULT_PLATFORM_HEALTH_AUTH_ENV,
        help=f"Bearer-token env var for platform health API calls (default: {DEFAULT_PLATFORM_HEALTH_AUTH_ENV})",
    )
    parser.add_argument("--identity-token-env", default="", help="Optional identity bearer-token env var; overrides --auth-token-env")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Thin local SDK/CLI prototype for the metadata, query-workflow, audit/public-report, and platform-health HTTP adapters.")
    sub = ap.add_subparsers(dest="command", required=True)

    metadata_health = sub.add_parser("metadata-health", help="GET /healthz from the metadata API")
    add_metadata_http_args(metadata_health)
    add_output_arg(metadata_health)

    metadata_job = sub.add_parser("metadata-job", help="GET /v1/jobs/<job_id> from the metadata API")
    add_metadata_http_args(metadata_job)
    metadata_job.add_argument("--job-id", required=True)
    add_output_arg(metadata_job)

    metadata_identity = sub.add_parser("metadata-identity", help="GET /v1/identity from the metadata API")
    add_metadata_http_args(metadata_identity)
    add_output_arg(metadata_identity)

    metadata_jobs = sub.add_parser("metadata-jobs", help="GET /v1/jobs from the metadata API")
    add_metadata_http_args(metadata_jobs)
    metadata_jobs.add_argument("--param", action="append", default=[], help="Query-string parameter as KEY=VALUE")
    add_output_arg(metadata_jobs)

    metadata_entity = sub.add_parser("metadata-entity", help="GET /v1/entities/<entity> from the metadata API")
    add_metadata_http_args(metadata_entity)
    metadata_entity.add_argument("--entity", required=True)
    metadata_entity.add_argument("--param", action="append", default=[], help="Query-string parameter as KEY=VALUE")
    add_output_arg(metadata_entity)

    query_health = sub.add_parser("query-health", help="GET /healthz from the query-workflow API")
    add_query_http_args(query_health)
    add_output_arg(query_health)

    query_submit = sub.add_parser("query-submit", help="POST a request to the query-workflow API")
    add_query_http_args(query_submit)
    query_submit.add_argument("--request-file", required=True, help="JSON request file")
    query_submit.add_argument("--request-base-dir", default="", help="Optional absolute request base dir for path resolution")
    query_submit.add_argument("--execute", action="store_true", help="Call /execute instead of /dry-run")
    add_output_arg(query_submit)

    audit_health = sub.add_parser("audit-health", help="GET /healthz from the audit/public-report API")
    add_audit_http_args(audit_health)
    add_output_arg(audit_health)

    audit_public_report = sub.add_parser("audit-public-report", help="GET /v1/public-report from the audit/public-report API")
    add_audit_http_args(audit_public_report)
    add_output_arg(audit_public_report)

    audit_chain = sub.add_parser("audit-chain", help="GET /v1/audit-chain from the audit/public-report API")
    add_audit_http_args(audit_chain)
    add_output_arg(audit_chain)

    audit_observability = sub.add_parser("audit-observability", help="GET /v1/observability from the audit/public-report API")
    add_audit_http_args(audit_observability)
    add_output_arg(audit_observability)

    audit_catalog_lineage = sub.add_parser("audit-catalog-lineage", help="GET /v1/catalog-lineage from the audit/public-report API")
    add_audit_http_args(audit_catalog_lineage)
    audit_catalog_lineage.add_argument("--include-paths", action="store_true", help="Request path-level lineage in the response")
    add_output_arg(audit_catalog_lineage)

    platform_api_health = sub.add_parser("platform-api-health", help="GET /healthz from the platform health API")
    add_platform_health_http_args(platform_api_health)
    add_output_arg(platform_api_health)

    platform_health = sub.add_parser("platform-health", help="GET /v1/platform-health from the platform health API")
    add_platform_health_http_args(platform_health)
    platform_health.add_argument("--param", action="append", default=[], help="Query-string parameter as KEY=VALUE")
    add_output_arg(platform_health)

    return ap


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "metadata-health":
        payload, exit_code = request_json(url=build_url(args.base_url, "/healthz"), method="GET")
        write_output(payload, args.output_file)
        return exit_code

    if args.command == "metadata-job":
        payload, exit_code = request_json(
            url=build_url(args.base_url, f"/v1/jobs/{args.job_id}"),
            method="GET",
            auth_token=resolve_request_auth_token(auth_token_env=args.auth_token_env, identity_token_env=args.identity_token_env),
        )
        write_output(payload, args.output_file)
        return exit_code

    if args.command == "metadata-identity":
        payload, exit_code = request_json(
            url=build_url(args.base_url, "/v1/identity"),
            method="GET",
            auth_token=resolve_request_auth_token(auth_token_env=args.auth_token_env, identity_token_env=args.identity_token_env),
        )
        write_output(payload, args.output_file)
        return exit_code

    if args.command == "metadata-jobs":
        payload, exit_code = request_json(
            url=build_url(args.base_url, "/v1/jobs", parse_params(args.param)),
            method="GET",
            auth_token=resolve_request_auth_token(auth_token_env=args.auth_token_env, identity_token_env=args.identity_token_env),
        )
        write_output(payload, args.output_file)
        return exit_code

    if args.command == "metadata-entity":
        payload, exit_code = request_json(
            url=build_url(args.base_url, f"/v1/entities/{args.entity}", parse_params(args.param)),
            method="GET",
            auth_token=resolve_request_auth_token(auth_token_env=args.auth_token_env, identity_token_env=args.identity_token_env),
        )
        write_output(payload, args.output_file)
        return exit_code

    if args.command == "query-health":
        payload, exit_code = request_json(url=build_url(args.base_url, "/healthz"), method="GET")
        write_output(payload, args.output_file)
        return exit_code

    if args.command == "query-submit":
        request_file = Path(args.request_file)
        if not request_file.is_file():
            raise SystemExit(f"[ERROR] request file does not exist: {request_file}")
        request_base_dir = args.request_base_dir or str(request_file.resolve().parent)
        headers = {}
        if request_base_dir:
            request_dir = Path(request_base_dir).expanduser()
            if not request_dir.is_absolute():
                raise SystemExit("[ERROR] --request-base-dir must be an absolute path when provided")
            headers["X-Request-Base-Dir"] = str(request_dir)
        path = "/v1/query-workflows/execute" if args.execute else "/v1/query-workflows/dry-run"
        payload, exit_code = request_json(
            url=build_url(args.base_url, path),
            method="POST",
            auth_token=resolve_request_auth_token(auth_token_env=args.auth_token_env, identity_token_env=args.identity_token_env),
            json_body=read_json(str(request_file)),
            extra_headers=headers,
        )
        write_output(payload, args.output_file)
        return exit_code

    if args.command == "audit-health":
        payload, exit_code = request_json(url=build_url(args.base_url, "/healthz"), method="GET")
        write_output(payload, args.output_file)
        return exit_code

    if args.command == "audit-public-report":
        payload, exit_code = request_json(
            url=build_url(args.base_url, "/v1/public-report"),
            method="GET",
            auth_token=resolve_request_auth_token(auth_token_env=args.auth_token_env, identity_token_env=args.identity_token_env),
        )
        write_output(payload, args.output_file)
        return exit_code

    if args.command == "audit-chain":
        payload, exit_code = request_json(
            url=build_url(args.base_url, "/v1/audit-chain"),
            method="GET",
            auth_token=resolve_request_auth_token(auth_token_env=args.auth_token_env, identity_token_env=args.identity_token_env),
        )
        write_output(payload, args.output_file)
        return exit_code

    if args.command == "audit-observability":
        payload, exit_code = request_json(
            url=build_url(args.base_url, "/v1/observability"),
            method="GET",
            auth_token=resolve_request_auth_token(auth_token_env=args.auth_token_env, identity_token_env=args.identity_token_env),
        )
        write_output(payload, args.output_file)
        return exit_code

    if args.command == "audit-catalog-lineage":
        params = [("include_paths", "true")] if args.include_paths else []
        payload, exit_code = request_json(
            url=build_url(args.base_url, "/v1/catalog-lineage", params),
            method="GET",
            auth_token=resolve_request_auth_token(auth_token_env=args.auth_token_env, identity_token_env=args.identity_token_env),
        )
        write_output(payload, args.output_file)
        return exit_code

    if args.command == "platform-api-health":
        payload, exit_code = request_json(url=build_url(args.base_url, "/healthz"), method="GET")
        write_output(payload, args.output_file)
        return exit_code

    if args.command == "platform-health":
        payload, exit_code = request_json(
            url=build_url(args.base_url, "/v1/platform-health", parse_params(args.param)),
            method="GET",
            auth_token=resolve_request_auth_token(auth_token_env=args.auth_token_env, identity_token_env=args.identity_token_env),
        )
        write_output(payload, args.output_file)
        return exit_code

    raise SystemExit(f"[ERROR] unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
