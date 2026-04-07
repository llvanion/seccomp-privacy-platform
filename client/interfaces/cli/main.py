from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from client.adapters.gateway.http_gateway_adapter import GatewayRequestError
from client.app.bootstrap import build_client_service


def _print_output(data: dict[str, Any], output: str) -> None:
    if output == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _parse_records(records_json: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(records_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"records_json is not valid JSON: {exc}") from exc
    if not isinstance(value, list):
        raise ValueError("records_json must be a JSON array")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="client-cli", description="Unified privacy platform client CLI")
    parser.add_argument("--gateway-base-url", default=None, help="Gateway base URL")
    parser.add_argument("--timeout", type=int, default=None, help="Request timeout seconds")
    parser.add_argument("--output", choices=["json", "table"], default="json")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health")

    attr = sub.add_parser("attribution-run")
    attr.add_argument("--job-id", required=True)
    attr.add_argument("--start-ts", required=True, type=int)
    attr.add_argument("--end-ts", required=True, type=int)
    attr.add_argument("--caller", required=True)
    attr.add_argument("--k", type=int, default=20)
    attr.add_argument("--n", type=int, default=5)
    attr.add_argument("--value-mode", default="count")
    attr.add_argument("--out-dir", default=None)

    se_build = sub.add_parser("se-build-index")
    se_build.add_argument("--index-name", required=True)
    se_build.add_argument("--records-json", required=True, help="JSON array for records")

    se_search = sub.add_parser("se-search")
    se_search.add_argument("--index-name", required=True)
    se_search.add_argument("--keyword", required=True)

    token_issue = sub.add_parser("token-issue")
    token_issue.add_argument("--actor", required=True)
    token_issue.add_argument("--scopes", required=True, help="Comma-separated scopes")
    token_issue.add_argument("--resource-id", default=None)
    token_issue.add_argument("--expire-seconds", type=int, default=None)

    token_revoke = sub.add_parser("token-revoke")
    token_revoke.add_argument("--revoked-by", required=True)
    token_revoke.add_argument("--reason", required=True)
    token_revoke.add_argument("--jti", default=None)
    token_revoke.add_argument("--token", default=None)

    audit = sub.add_parser("audit-query")
    audit.add_argument("--action", default=None)
    audit.add_argument("--actor", default=None)
    audit.add_argument("--start-ts", default=None)
    audit.add_argument("--end-ts", default=None)
    audit.add_argument("--limit", type=int, default=100)

    sensitive = sub.add_parser("sensitive-read")
    sensitive.add_argument("--order-id", required=True)
    sensitive.add_argument("--token", required=True, help="Bearer token value")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _, service = build_client_service(
        gateway_base_url=args.gateway_base_url,
        timeout_seconds=args.timeout,
    )

    try:
        if args.command == "health":
            result = service.health()
        elif args.command == "attribution-run":
            result = service.attribution_run(
                job_id=args.job_id,
                start_ts=args.start_ts,
                end_ts=args.end_ts,
                caller=args.caller,
                k=args.k,
                n=args.n,
                value_mode=args.value_mode,
                out_dir=args.out_dir,
            )
        elif args.command == "se-build-index":
            records = _parse_records(args.records_json)
            result = service.se_build_index(index_name=args.index_name, records=records)
        elif args.command == "se-search":
            result = service.se_search(index_name=args.index_name, keyword=args.keyword)
        elif args.command == "token-issue":
            scopes = [item.strip() for item in args.scopes.split(",") if item.strip()]
            result = service.token_issue(
                actor=args.actor,
                scopes=scopes,
                resource_id=args.resource_id,
                expire_seconds=args.expire_seconds,
            )
        elif args.command == "token-revoke":
            if not args.jti and not args.token:
                raise ValueError("either --jti or --token must be provided")
            result = service.token_revoke(
                revoked_by=args.revoked_by,
                reason=args.reason,
                jti=args.jti,
                token=args.token,
            )
        elif args.command == "audit-query":
            result = service.audit_query(
                action=args.action,
                actor=args.actor,
                start_ts=args.start_ts,
                end_ts=args.end_ts,
                limit=args.limit,
            )
        elif args.command == "sensitive-read":
            result = service.sensitive_read(order_id=args.order_id, bearer_token=args.token)
        else:
            parser.print_help()
            return 2
    except (GatewayRequestError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    _print_output(result, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
