#!/usr/bin/env python3
"""Request an OIDC client-credentials token from a live issuer."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.metadata_db import utc_now  # noqa: E402

REPORT_SCHEMA = "oidc_client_credentials_report/v1"


def _request_token(*, token_endpoint: str, client_id: str, client_secret: str, scope: str) -> dict[str, Any]:
    form = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if scope:
        form["scope"] = scope
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        token_endpoint,
        data=data,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("token endpoint returned non-object JSON")
    return payload


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    mode = "execute" if args.execute else "dry_run"
    try:
        token_type = None
        expires_in = None
        token_redacted = None
        if args.execute:
            client_secret = os.environ.get(args.client_secret_env, "")
            if not client_secret:
                raise PermissionError(f"client secret env is unset: {args.client_secret_env}")
            payload = _request_token(
                token_endpoint=args.token_endpoint,
                client_id=args.client_id,
                client_secret=client_secret,
                scope=args.scope,
            )
            access_token = str(payload.get("access_token") or "")
            if not access_token:
                raise RuntimeError("token endpoint did not return access_token")
            if args.token_output_file:
                Path(args.token_output_file).write_text(access_token, encoding="utf-8")
            token_type = str(payload.get("token_type") or "")
            expires_in = int(payload.get("expires_in") or 0)
            token_redacted = "REDACTED"
        return {
            "schema": REPORT_SCHEMA,
            "generated_at_utc": utc_now(),
            "mode": mode,
            "ok": True,
            "error": None,
            "token_endpoint": args.token_endpoint,
            "client_id": args.client_id,
            "scope": args.scope or None,
            "token_type": token_type,
            "expires_in": expires_in,
            "access_token_redacted": token_redacted,
            "token_output_file": str(Path(args.token_output_file).resolve()) if args.token_output_file else None,
        }
    except Exception as exc:
        return {
            "schema": REPORT_SCHEMA,
            "generated_at_utc": utc_now(),
            "mode": mode,
            "ok": False,
            "error": str(exc),
            "token_endpoint": args.token_endpoint,
            "client_id": args.client_id,
            "scope": args.scope or None,
            "token_type": None,
            "expires_in": None,
            "access_token_redacted": None,
            "token_output_file": None,
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="Request OIDC client-credentials token")
    ap.add_argument("--token-endpoint", required=True)
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--client-secret-env", default="OIDC_CLIENT_SECRET")
    ap.add_argument("--scope", default="")
    ap.add_argument("--token-output-file", default="")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--output", default="")
    ap.add_argument("--assert-ok", action="store_true")
    args = ap.parse_args()
    report = build_report(args)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 1 if args.assert_ok and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
