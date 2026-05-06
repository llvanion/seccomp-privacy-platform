#!/usr/bin/env python3
import argparse
import json
import os

from api_identity import (
    build_identity_resolution_payload,
    resolve_identity_context,
    resolve_identity_subject_context,
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Resolve a bearer token or issuer/subject pair into the platform caller identity context.")
    ap.add_argument("--db-path", default="")
    ap.add_argument("--db-dsn", default="")
    ap.add_argument("--identity-token-config", default="", help="Required when resolving via bearer token")
    ap.add_argument("--bearer-token-env", default="", help="Environment variable containing the bearer token to resolve")
    ap.add_argument("--issuer", default="", help="Resolve directly via issuer + subject instead of bearer token")
    ap.add_argument("--subject", default="", help="Resolve directly via issuer + subject instead of bearer token")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if not args.db_path and not args.db_dsn:
        raise SystemExit("[ERROR] one of --db-path or --db-dsn is required")
    if args.bearer_token_env:
        if args.issuer or args.subject:
            raise SystemExit("[ERROR] --bearer-token-env cannot be combined with --issuer/--subject")
        if not args.identity_token_config:
            raise SystemExit("[ERROR] --bearer-token-env requires --identity-token-config")
        bearer_token = os.environ.get(args.bearer_token_env, "")
        if not bearer_token:
            raise SystemExit(f"[ERROR] environment variable {args.bearer_token_env} is not set")
        payload = build_identity_resolution_payload(
            resolve_identity_context(
                db_path=args.db_path,
                db_dsn=args.db_dsn,
                identity_token_config=args.identity_token_config,
                bearer_token=bearer_token,
            ),
            resolution_mode="bearer_token",
        )
    else:
        if not args.subject:
            raise SystemExit("[ERROR] either --bearer-token-env or --issuer/--subject is required")
        payload = build_identity_resolution_payload(
            resolve_identity_subject_context(
                db_path=args.db_path,
                db_dsn=args.db_dsn,
                issuer=args.issuer,
                subject=args.subject,
            ),
            resolution_mode="subject_lookup",
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
