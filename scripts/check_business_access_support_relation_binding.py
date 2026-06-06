#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from api_identity import resolve_identity_context
from check_business_access_api_smoke import init_db
from serve_metadata_api import DEFAULT_BUSINESS_ACCESS_POLICY, MetadataApiHandler


def main() -> int:
    ap = argparse.ArgumentParser(description="Freeze repo-side support relation-binding evidence without relying on loopback HTTP sockets.")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="support_relation_binding.") as tmp_raw:
        tmp = Path(tmp_raw)
        db_path = tmp / "metadata.sqlite"
        init_db(db_path)

        token_env = "BUSINESS_ACCESS_API_SMOKE_SUPPORT_TOKEN"
        token = "example-business-access-smoke-support-token"
        os.environ[token_env] = token
        identity_config = tmp / "identity_tokens.json"
        identity_config.write_text(
            json.dumps(
                {
                    "schema": "api_identity_token_map/v1",
                    "tokens": [
                        {"token_env": token_env, "issuer": "local", "subject": "user:support"},
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        identity = resolve_identity_context(
            db_path=str(db_path),
            identity_token_config=str(identity_config),
            bearer_token=token,
        )

        class _Server:
            pass

        server = _Server()
        server.db_path = str(db_path)
        server.db_dsn = ""
        server.db_read_dsn = ""
        server.business_access_policy = str(DEFAULT_BUSINESS_ACCESS_POLICY)
        handler = object.__new__(MetadataApiHandler)
        handler.server = server

        report = handler._business_access_check(
            {
                "role": "customer_service_agent",
                "entity": "orders",
                "fields": ["orders.order_id", "orders.buyer_email"],
                "purpose": "support_case",
                "relationship": "assigned_support_case",
                "scope": {
                    "tenant_id": "commerce_tenant",
                    "order_id": "o-1",
                    "case_id": "case-1",
                },
            },
            identity=identity,
        )

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
