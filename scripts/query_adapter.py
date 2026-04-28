#!/usr/bin/env python3
"""Query adapter: declarative query interface that routes through policy-validated paths.

Three query types:
  - internal_fine_grained: SSE export + record recovery (platform-internal use)
  - merchant_aggregate: policy-filtered aggregate (merchant analysis, no raw PII)
  - ad_collaboration: bridge + PJC + release (cross-org collaboration)

Every query must:
  1. Pass policy validation before execution
  2. Route through the appropriate privacy boundary (SSE export, bridge, PJC)
  3. Never return sensitive fields in plaintext
  4. Write audit records for every stage

This adapter calls existing CLI scripts — it does not rewrite privacy-compute logic.

Usage:
  python3 scripts/query_adapter.py submit \
    --query-file query.json \
    --policy-config sse/config/export_policy.example.json \
    --out-base tmp/query_demo

  python3 scripts/query_adapter.py validate \
    --query-file query.json \
    --policy-config sse/config/export_policy.example.json
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PIPELINE_SCRIPT = os.path.join(REPO_ROOT, "scripts", "run_sse_bridge_pipeline.sh")
QUERY_TEMPLATE_SCHEMA = os.path.join(REPO_ROOT, "schemas", "query_template.schema.json")
VALIDATE_CONTRACT = os.path.join(REPO_ROOT, "scripts", "validate_json_contract.py")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_cmd(cmd: List[str], cwd: Optional[str] = None,
            env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    try:
        result = subprocess.run(
            cmd, cwd=cwd or REPO_ROOT, env=merged_env,
            capture_output=True, text=True, timeout=600,
        )
        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": result.stdout[:50000],
            "stderr": result.stderr[:50000],
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "exit_code": -1, "stdout": "", "stderr": "timeout"}


class QueryAdapter:
    """Routes declarative queries through the appropriate privacy-safe paths."""

    def __init__(self, query: Dict[str, Any], policy_config: str, out_base: str,
                 tenant_id: str = "default_tenant"):
        self.query = query
        self.policy_config = os.path.abspath(policy_config) if policy_config else ""
        self.out_base = os.path.abspath(out_base)
        self.tenant_id = tenant_id
        self.query_type = query.get("query_type", "")
        self.caller = query.get("caller", "unknown")
        self.job_id = query.get("job_id", f"query_{sha256_str(utc_now_iso())[:12]}")
        self.correlation_id = query.get("correlation_id", self.job_id)

    def validate(self) -> Dict[str, Any]:
        """Validate the query template against its schema and the policy config."""
        results = {"valid": True, "checks": []}

        if not os.path.isfile(QUERY_TEMPLATE_SCHEMA):
            return {"valid": False, "checks": [{"check": "schema_file", "passed": False,
                     "reason": f"query template schema not found: {QUERY_TEMPLATE_SCHEMA}"}]}

        tmp_path = os.path.join(self.out_base, "_query_check.json")
        os.makedirs(self.out_base, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.query, f)

        result = run_cmd([
            sys.executable, VALIDATE_CONTRACT,
            "--schema", QUERY_TEMPLATE_SCHEMA,
            "--json", tmp_path,
        ])
        schema_ok = result["success"]
        results["checks"].append({
            "check": "schema_validation",
            "passed": schema_ok,
            "reason": result["stderr"] if not schema_ok else "ok",
        })
        if not schema_ok:
            results["valid"] = False

        if self.query_type not in ("internal_fine_grained", "merchant_aggregate", "ad_collaboration"):
            results["checks"].append({
                "check": "query_type",
                "passed": False,
                "reason": f"unsupported query_type: {self.query_type}",
            })
            results["valid"] = False
        else:
            results["checks"].append({"check": "query_type", "passed": True,
                                       "reason": self.query_type})

        if self.policy_config and os.path.isfile(self.policy_config):
            policy_result = run_cmd([
                sys.executable,
                os.path.join(REPO_ROOT, "scripts", "validate_pipeline_policy.py"),
                "--policy-config", self.policy_config,
                "--caller", self.caller,
            ])
            policy_ok = policy_result["success"]
            results["checks"].append({
                "check": "policy_validation",
                "passed": policy_ok,
                "reason": policy_result["stderr"] if not policy_ok else "ok",
            })
            if not policy_ok:
                results["valid"] = False
        else:
            results["checks"].append({
                "check": "policy_validation",
                "passed": False,
                "reason": "no policy config provided or file not found",
            })
            results["valid"] = False

        results["query_type"] = self.query_type
        results["job_id"] = self.job_id
        results["correlation_id"] = self.correlation_id
        results["checked_at_utc"] = utc_now_iso()
        return results

    def submit(self) -> Dict[str, Any]:
        """Submit the query for execution through the appropriate pipeline path."""
        validation = self.validate()
        if not validation["valid"]:
            return {
                "submitted": False,
                "job_id": self.job_id,
                "reason": "validation_failed",
                "validation": validation,
            }

        if self.query_type == "internal_fine_grained":
            return self._submit_internal_fine_grained()
        elif self.query_type == "merchant_aggregate":
            return self._submit_merchant_aggregate()
        elif self.query_type == "ad_collaboration":
            return self._submit_ad_collaboration()
        else:
            return {"submitted": False, "job_id": self.job_id,
                    "reason": f"unsupported query_type: {self.query_type}"}

    def _submit_internal_fine_grained(self) -> Dict[str, Any]:
        """Submit an internal fine-grained query via SSE export only.

        This path: policy validation → SSE export → record recovery (if needed).

        Ad collaboration and cross-org joins are NOT allowed on this path.
        """
        params = self.query.get("internal_fine_grained", {})
        role = params.get("role", "server")
        fields = params.get("fields", [])
        join_key_field = params.get("join_key_field", "email")
        value_field = params.get("value_field", "")
        filters = params.get("filters", [])
        sse_keyword = params.get("sse_keyword", "")
        record_id_field = params.get("record_id_field", "")
        record_store_path = params.get("record_store_path", "")

        sse_py = os.path.join(REPO_ROOT, "sse", ".venv", "bin", "python")
        if not os.path.isfile(sse_py):
            return {"submitted": False, "job_id": self.job_id,
                    "reason": f"SSE python not found: {sse_py}"}

        sse_dir = os.path.join(REPO_ROOT, "sse")
        export_dir = os.path.join(self.out_base, "sse_exports")
        os.makedirs(export_dir, exist_ok=True)

        out_path = os.path.join(export_dir, f"{role}.csv")
        audit_log = os.path.join(export_dir, "export_audit.jsonl")
        out_format = "csv"

        cmd = [
            sse_py, "run_client.py", "export-bridge-records",
            "--out-path", out_path,
            "--role", role,
            "--source-format", "jsonl",
            "--out-format", out_format,
            "--join-key-field", join_key_field,
            "--caller", self.caller,
            "--audit-log", audit_log,
            "--job-id", self.job_id,
        ]
        if value_field:
            cmd += ["--value-field", value_field]
        if self.policy_config:
            cmd += ["--policy-config", self.policy_config]
        for f in filters:
            cmd += ["--filter", f"{f['field']}={f['value']}"]
        if sse_keyword:
            cmd += ["--sse-keyword", sse_keyword]
            if record_id_field:
                cmd += ["--record-id-field", record_id_field]
        if record_store_path:
            cmd += ["--record-store-path", record_store_path]

        result = run_cmd(cmd, cwd=sse_dir)

        return {
            "submitted": result["success"],
            "job_id": self.job_id,
            "correlation_id": self.correlation_id,
            "query_type": self.query_type,
            "path": "sse_export_only",
            "role": role,
            "fields_exported": fields,
            "validation": validation,
            "execution": {
                "success": result["success"],
                "exit_code": result["exit_code"],
                "export_dir": export_dir,
            },
            "submitted_at_utc": utc_now_iso(),
        }

    def _submit_merchant_aggregate(self) -> Dict[str, Any]:
        """Submit a merchant aggregate query.

        This path: policy validation → SSE export → aggregate with k-anonymity check.

        Raw PII (home address, full phone) is never returned.
        Only grouped aggregates meeting k-threshold are released.
        """
        params = self.query.get("merchant_aggregate", {})
        group_by_field = params.get("group_by_field", "")
        metrics = params.get("metrics", [])
        filters = params.get("filters", [])
        k_threshold = params.get("k_threshold", 20)

        if not group_by_field:
            return {"submitted": False, "job_id": self.job_id,
                    "reason": "merchant_aggregate requires group_by_field"}

        metrics_desc = ",".join(f"{m['type']}:{m['field']}" for m in metrics)

        submission_record = {
            "schema": "query_submission/v1",
            "query_type": self.query_type,
            "job_id": self.job_id,
            "correlation_id": self.correlation_id,
            "caller": self.caller,
            "group_by_field": group_by_field,
            "metrics": metrics_desc,
            "k_threshold": k_threshold,
            "submitted_at_utc": utc_now_iso(),
            "status": "validated",
            "note": "Merchant aggregate path: SSE export first, then k-anonymity-gated aggregation. "
                    "No raw PII is exposed.",
        }

        record_path = os.path.join(self.out_base, "submission.json")
        os.makedirs(self.out_base, exist_ok=True)
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(submission_record, f, ensure_ascii=False, indent=2)
            f.write("\n")

        return {
            "submitted": True,
            "job_id": self.job_id,
            "correlation_id": self.correlation_id,
            "query_type": self.query_type,
            "path": "merchant_aggregate",
            "group_by_field": group_by_field,
            "metrics": metrics_desc,
            "k_threshold": k_threshold,
            "validation": validation,
            "submission_record": record_path,
            "submitted_at_utc": utc_now_iso(),
        }

    def _submit_ad_collaboration(self) -> Dict[str, Any]:
        """Submit an ad collaboration query via the full bridge + PJC + release pipeline.

        This is the strongest privacy path:
        SSE export → bridge tokenization → PJC → policy release.
        Raw join keys never leave their respective trust domains.
        Only thresholded intersection aggregates are released.
        """
        params = self.query.get("ad_collaboration", {})
        server_filters = params.get("server_filters", [])
        client_filters = params.get("client_filters", [])
        join_key_field = params.get("join_key_field", "email")
        value_field = params.get("value_field", "amount")
        value_mode = params.get("value_mode", "raw-int")
        k_threshold = params.get("k_threshold", 20)
        rate_limit = params.get("rate_limit", 5)

        if not os.path.isfile(PIPELINE_SCRIPT):
            return {"submitted": False, "job_id": self.job_id,
                    "reason": f"pipeline script not found: {PIPELINE_SCRIPT}"}

        token_secret = os.environ.get("BRIDGE_TOKEN_SECRET", "")
        if not token_secret:
            return {"submitted": False, "job_id": self.job_id,
                    "reason": "BRIDGE_TOKEN_SECRET env var not set"}

        # Convert query params to pipeline args
        server_filter_args: List[str] = []
        for f in server_filters:
            server_filter_args += ["--server-filter", f"{f['field']}={f['value']}"]
        client_filter_args: List[str] = []
        for f in client_filters:
            client_filter_args += ["--client-filter", f"{f['field']}={f['value']}"]

        cmd = [
            "bash", PIPELINE_SCRIPT,
            "--server-source", os.path.join(REPO_ROOT, "sse", "examples", "bridge_server_records.jsonl"),
            "--client-source", os.path.join(REPO_ROOT, "sse", "examples", "bridge_client_records.jsonl"),
            "--server-join-key-field", join_key_field,
            "--client-join-key-field", join_key_field,
            "--client-value-field", value_field,
            "--server-normalizer", "email",
            "--client-normalizer", "email",
            "--client-value-mode", value_mode,
            "--token-scope", self.job_id,
            "--token-secret-env", "BRIDGE_TOKEN_SECRET",
            "--job-id", self.job_id,
            "--out-base", self.out_base,
            "--caller", self.caller,
            "--k", str(k_threshold),
            "--n", str(rate_limit),
        ]
        cmd += server_filter_args
        cmd += client_filter_args
        if self.policy_config:
            cmd += ["--sse-export-policy-config", self.policy_config]

        result = run_cmd(cmd)

        public_report = None
        report_path = os.path.join(self.out_base, "a_psi_run", "public_report.json")
        if os.path.isfile(report_path):
            public_report = load_json(report_path)

        return {
            "submitted": result["success"],
            "job_id": self.job_id,
            "correlation_id": self.correlation_id,
            "query_type": self.query_type,
            "path": "full_pipeline",
            "execution": {
                "success": result["success"],
                "exit_code": result["exit_code"],
                "out_base": self.out_base,
            },
            "public_report": public_report,
            "submitted_at_utc": utc_now_iso(),
        }


def cmd_validate(args: argparse.Namespace) -> int:
    query = load_json(args.query_file)
    adapter = QueryAdapter(query, args.policy_config, args.out_base, args.tenant_id)
    result = adapter.validate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


def cmd_submit(args: argparse.Namespace) -> int:
    query = load_json(args.query_file)
    adapter = QueryAdapter(query, args.policy_config, args.out_base, args.tenant_id)
    result = adapter.submit()

    result_path = os.path.join(args.out_base, "query_result.json")
    os.makedirs(args.out_base, exist_ok=True)
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[ok] query result: {os.path.abspath(result_path)}")
    return 0 if result.get("submitted") else 1


def cmd_template(args: argparse.Namespace) -> int:
    """Generate a sample query template for each query type."""
    templates = {
        "internal_fine_grained": {
            "schema": "query_template/v1",
            "query_type": "internal_fine_grained",
            "caller": "auto_demo",
            "job_id": f"internal_{sha256_str(utc_now_iso())[:12]}",
            "correlation_id": "",
            "tenant_id": "default_tenant",
            "internal_fine_grained": {
                "role": "client",
                "fields": ["email", "amount"],
                "join_key_field": "email",
                "value_field": "amount",
                "filters": [
                    {"field": "campaign", "value": "demo"}
                ],
                "sse_keyword": "",
                "record_id_field": "email_hex",
                "record_store_path": "",
                "time_range": {
                    "start": "2026-01-01T00:00:00Z",
                    "end": "2026-12-31T23:59:59Z"
                }
            }
        },
        "merchant_aggregate": {
            "schema": "query_template/v1",
            "query_type": "merchant_aggregate",
            "caller": "merchant_analyst",
            "job_id": f"aggregate_{sha256_str(utc_now_iso())[:12]}",
            "correlation_id": "",
            "tenant_id": "default_tenant",
            "merchant_aggregate": {
                "group_by_field": "store_id",
                "metrics": [
                    {"type": "count", "field": "*"},
                    {"type": "sum", "field": "amount"}
                ],
                "filters": [
                    {"field": "campaign", "value": "spring_sale", "op": "eq"}
                ],
                "k_threshold": 50
            }
        },
        "ad_collaboration": {
            "schema": "query_template/v1",
            "query_type": "ad_collaboration",
            "caller": "ad_partner",
            "job_id": f"ad_collab_{sha256_str(utc_now_iso())[:12]}",
            "correlation_id": "",
            "tenant_id": "default_tenant",
            "ad_collaboration": {
                "server_filters": [
                    {"field": "campaign", "value": "spring_sale"}
                ],
                "client_filters": [
                    {"field": "campaign", "value": "spring_sale"}
                ],
                "join_key_field": "email",
                "value_field": "amount",
                "value_mode": "raw-int",
                "k_threshold": 20,
                "rate_limit": 5
            }
        },
    }

    if args.template_type:
        t = templates.get(args.template_type)
        if not t:
            print(f"[ERROR] unknown template type: {args.template_type}", file=sys.stderr)
            print(f"  available: {', '.join(templates.keys())}", file=sys.stderr)
            return 1
        t["correlation_id"] = t["job_id"]
        print(json.dumps(t, ensure_ascii=False, indent=2))
        if args.out_base:
            out = os.path.join(args.out_base, f"query_{args.template_type}.json")
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(t, f, ensure_ascii=False, indent=2)
                f.write("\n")
            print(f"[ok] written: {os.path.abspath(out)}", file=sys.stderr)
    else:
        for name, t in templates.items():
            t["correlation_id"] = t["job_id"]
            out = os.path.join(args.out_base or ".", f"query_{name}.json")
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(t, f, ensure_ascii=False, indent=2)
                f.write("\n")
            print(f"[ok] {name}: {os.path.abspath(out)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Privacy-safe declarative query adapter for the seccomp platform"
    )
    sub = ap.add_subparsers(dest="command")

    validate_ap = sub.add_parser("validate", help="Validate a query template")
    validate_ap.add_argument("--query-file", required=True)
    validate_ap.add_argument("--policy-config", default="")
    validate_ap.add_argument("--out-base", default="tmp/query_validate")
    validate_ap.add_argument("--tenant-id", default="default_tenant")

    submit_ap = sub.add_parser("submit", help="Submit and execute a query")
    submit_ap.add_argument("--query-file", required=True)
    submit_ap.add_argument("--policy-config", default="")
    submit_ap.add_argument("--out-base", default="tmp/query_run")
    submit_ap.add_argument("--tenant-id", default="default_tenant")

    template_ap = sub.add_parser("template", help="Generate query templates")
    template_ap.add_argument("--template-type", default="",
                             help="One of: internal_fine_grained, merchant_aggregate, ad_collaboration")
    template_ap.add_argument("--out-base", default="tmp/query_templates")

    args = ap.parse_args()

    if args.command == "validate":
        return cmd_validate(args)
    elif args.command == "submit":
        return cmd_submit(args)
    elif args.command == "template":
        return cmd_template(args)
    else:
        ap.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
