#!/usr/bin/env python3
"""Admin CLI prototype for the seccomp-privacy-platform.

Provides a management interface for:
  - Job submission and status
  - Audit chain query
  - Public report query
  - Catalog browse
  - Runbook generation
  - Telemetry summary

This CLI only calls control-plane read APIs and job/audit adapters.
It does NOT directly access:
  - Encrypted record store reader
  - Bridge token secret
  - PJC raw binary
  - Raw recovery service

Usage:
  python3 scripts/admin_cli.py job status --job-id auto_demo_job --out-base tmp/sse_bridge_pipeline_demo
  python3 scripts/admin_cli.py audit show --out-base tmp/sse_bridge_pipeline_demo
  python3 scripts/admin_cli.py report public --out-base tmp/sse_bridge_pipeline_demo
  python3 scripts/admin_cli.py catalog list --out-base tmp/sse_bridge_pipeline_demo
  python3 scripts/admin_cli.py runbook generate --out-base tmp/sse_bridge_pipeline_demo
  python3 scripts/admin_cli.py telemetry summary --out-base tmp/sse_bridge_pipeline_demo
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    records = []
    if not path or not os.path.isfile(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def resolve_out_base(args: argparse.Namespace) -> str:
    return os.path.abspath(args.out_base)


# ── Job commands ──────────────────────────────────────────────


def cmd_job_status(args: argparse.Namespace) -> int:
    out_base = resolve_out_base(args)
    audit_chain = load_json(os.path.join(out_base, "audit_chain.json"))
    public_report = load_json(os.path.join(out_base, "a_psi_run", "public_report.json"))
    pjc_result = load_json(os.path.join(out_base, "a_psi_run", "attribution_result.json"))

    if not audit_chain:
        print(f"[ERROR] audit_chain.json not found in {out_base}", file=sys.stderr)
        return 1

    print(f"Job: {audit_chain.get('job_id', 'unknown')}")
    print(f"Correlation: {audit_chain.get('correlation_id', 'unknown')}")
    print(f"Generated: {audit_chain.get('generated_at_utc', 'unknown')}")
    print()

    counts = audit_chain.get("counts", {})
    print("Audit Records:")
    for stream, count in counts.items():
        print(f"  {stream}: {count}")

    if pjc_result:
        print(f"\nPJC Result:")
        print(f"  Intersection size: {pjc_result.get('intersection_size', '?')}")
        print(f"  Intersection sum:  {pjc_result.get('intersection_sum', '?')}")

    if public_report:
        print(f"\nRelease Decision:")
        print(f"  Released: {public_report.get('released', False)}")
        print(f"  Reason:   {public_report.get('reason', 'unknown')} ({public_report.get('reason_code', '')})")
        print(f"  K threshold: {public_report.get('k_threshold', '?')}")
        print(f"  Rate limit:  {public_report.get('rate_limit_used', '?')}/{public_report.get('rate_limit_max', '?')}")

    return 0


def cmd_job_list(args: argparse.Namespace) -> int:
    out_base = resolve_out_base(args)
    if not os.path.isdir(out_base):
        print(f"Listing jobs under: {os.path.abspath(out_base)}")
        parent = os.path.dirname(out_base) if out_base else "tmp"
        if os.path.isdir(parent):
            for d in sorted(os.listdir(parent)):
                dpath = os.path.join(parent, d)
                if os.path.isdir(dpath):
                    chain = os.path.join(dpath, "audit_chain.json")
                    if os.path.isfile(chain):
                        data = load_json(chain)
                        if data:
                            print(f"  [{d}] job_id={data.get('job_id','?')} "
                                  f"generated={data.get('generated_at_utc','?')}")
    else:
        chain = load_json(os.path.join(out_base, "audit_chain.json"))
        if chain:
            print(f"  job_id={chain.get('job_id','?')} "
                  f"generated={chain.get('generated_at_utc','?')}")
    return 0


# ── Audit commands ────────────────────────────────────────────


def cmd_audit_show(args: argparse.Namespace) -> int:
    out_base = resolve_out_base(args)
    chain = load_json(os.path.join(out_base, "audit_chain.json"))
    if not chain:
        print(f"[ERROR] audit_chain.json not found in {out_base}", file=sys.stderr)
        return 1

    if args.format == "summary":
        print(f"Job: {chain.get('job_id', '?')}")
        print(f"Correlation: {chain.get('correlation_id', '?')}")
        print()
        for stream_name, records in [
            ("SSE Export", chain.get("sse_export_audit", [])),
            ("Record Recovery", chain.get("record_recovery_service_audit", [])),
            ("Bridge", chain.get("bridge_audit", [])),
            ("Policy", chain.get("policy_audit", [])),
            ("Key Access", chain.get("key_access_audit", [])),
        ]:
            if records:
                for r in records:
                    decision = r.get("decision", "?")
                    icon = "PASS" if decision == "allow" else "FAIL"
                    print(f"  [{icon}] {stream_name}: {r.get('reason_code','?')}")
    else:
        print(json.dumps(chain, ensure_ascii=False, indent=2))
    return 0


def cmd_audit_verify(args: argparse.Namespace) -> int:
    out_base = resolve_out_base(args)
    seal = load_json(os.path.join(out_base, "audit_chain.seal.json"))
    if not seal:
        print(f"[ERROR] audit_chain.seal.json not found in {out_base}", file=sys.stderr)
        return 1

    audit_sha = seal.get("audit_chain_sha256", "")
    hmac_sha = seal.get("hmac_sha256", "")

    print(f"Audit chain SHA-256: {audit_sha}")
    if hmac_sha:
        print(f"HMAC signature:      {hmac_sha[:32]}...")
        print(f"HMAC key env:        {seal.get('hmac_key_env', '?')}")
        print(f"HMAC verified:       {seal.get('hmac_verified', 'N/A')}")
    print(f"Schema:              {seal.get('schema', '?')}")
    print(f"Job ID:              {seal.get('job_id', '?')}")
    print(f"Generated:           {seal.get('generated_at_utc', '?')}")
    return 0


# ── Report commands ───────────────────────────────────────────


def cmd_report_public(args: argparse.Namespace) -> int:
    out_base = resolve_out_base(args)
    report = load_json(os.path.join(out_base, "a_psi_run", "public_report.json"))
    if not report:
        print(f"[ERROR] public_report.json not found in {out_base}", file=sys.stderr)
        return 1

    released = report.get("released", False)
    print(f"{'RELEASED' if released else 'WITHHELD'}")
    print(f"  Job ID:       {report.get('job_id', '?')}")
    print(f"  Caller:       {report.get('caller', '?')}")
    print(f"  Reason:       {report.get('reason', '?')} ({report.get('reason_code', '?')})")
    print(f"  K threshold:  {report.get('k_threshold', '?')}")
    print(f"  Rate limit:   {report.get('rate_limit_used', '?')}/{report.get('rate_limit_max', '?')}")
    print(f"  Conversions:  {report.get('conversions', '?')}")
    print(f"  Value sum:    {report.get('value_sum', '?')}")
    print(f"  AOV:          {report.get('aov', '?')}")
    print(f"  Policy:       {report.get('policy_version', '?')}")
    return 0


def cmd_report_list(args: argparse.Namespace) -> int:
    out_base = resolve_out_base(args)
    report = load_json(os.path.join(out_base, "a_psi_run", "public_report.json"))
    if not report:
        return 0
    released = "RELEASED" if report.get("released") else "WITHHELD"
    print(f"  [{released}] job={report.get('job_id','?')} "
          f"caller={report.get('caller','?')} "
          f"reason={report.get('reason_code','?')} "
          f"k={report.get('k_threshold','?')}")
    return 0


# ── Catalog commands ──────────────────────────────────────────


def cmd_catalog_list(args: argparse.Namespace) -> int:
    out_base = resolve_out_base(args)
    catalog_path = os.path.join(out_base, "catalog.jsonl")

    if not os.path.isfile(catalog_path):
        # Try to build catalog on the fly
        import subprocess
        result = subprocess.run([
            sys.executable,
            os.path.join(REPO_ROOT, "scripts", "catalog_adapter.py"),
            "--out-base", out_base,
            "--tenant-id", getattr(args, "tenant_id", "default_tenant"),
        ], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[ERROR] catalog.jsonl not found and catalog_adapter failed", file=sys.stderr)
            return 1
        catalog_path = os.path.join(out_base, "catalog.jsonl")

    entries = load_jsonl(catalog_path)
    if args.entry_type:
        entries = [e for e in entries if e.get("entry_type") == args.entry_type]

    for e in entries:
        eid = e.get("entry_id", "?")
        etype = e.get("entry_type", "?")
        if etype == "dataset":
            ds = e.get("dataset", {})
            print(f"  [dataset]     {ds.get('display_name', eid[:24])} "
                  f"(rows={ds.get('record_count', '?')}, "
                  f"source={ds.get('source_type', '?')})")
        elif etype == "job":
            j = e.get("job", {})
            print(f"  [job]         {j.get('job_id', '?')} "
                  f"caller={j.get('caller', '?')} "
                  f"status={j.get('status', '?')}")
        elif etype == "artifact":
            a = e.get("artifact", {})
            print(f"  [artifact]    {a.get('artifact_type', '?')} "
                  f"stage={a.get('stage', '?')} "
                  f"size={a.get('size_bytes', 0)}B")
        elif etype == "public_report":
            r = e.get("public_report_entry", {})
            print(f"  [report]      job={r.get('job_id', '?')} "
                  f"released={r.get('released', False)} "
                  f"k={r.get('k_threshold', '?')}")
        elif etype == "policy_binding":
            pb = e.get("policy_binding", {})
            print(f"  [policy]      config={os.path.basename(pb.get('policy_config_path', '?'))} "
                  f"roles={pb.get('allowed_roles', [])}")
        else:
            print(f"  [{etype}]  {eid[:48]}")

    print(f"\n{len(entries)} entries")
    return 0


# ── Runbook commands ──────────────────────────────────────────


def cmd_runbook_generate(args: argparse.Namespace) -> int:
    out_base = resolve_out_base(args)
    import subprocess
    result = subprocess.run([
        sys.executable,
        os.path.join(REPO_ROOT, "scripts", "generate_observability_runbook.py"),
        "--out-base", out_base,
    ] + (["--job-id", args.job_id] if args.job_id else []),
    capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return 1
    print(result.stdout)
    return 0


# ── Telemetry commands ────────────────────────────────────────


def cmd_telemetry_summary(args: argparse.Namespace) -> int:
    out_base = resolve_out_base(args)
    manifest = load_json(os.path.join(out_base, "telemetry_manifest.json"))

    if not manifest:
        print(f"[INFO] No telemetry manifest found; generating telemetry...")
        import subprocess
        result = subprocess.run([
            sys.executable,
            os.path.join(REPO_ROOT, "scripts", "telemetry_pipeline.py"),
            "--out-base", out_base,
            "--format", "otlp-jsonl",
        ], capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            return 1
        manifest = load_json(os.path.join(out_base, "telemetry_manifest.json"))

    if manifest:
        print(f"Telemetry Snapshot:")
        print(f"  Jobs tracked:   {manifest.get('job_count', 0)}")
        print(f"  Metrics emitted: {manifest.get('metric_count', 0)}")
        print(f"  Alerts:          {manifest.get('alert_count', 0)}")
        print(f"  Tenant:          {manifest.get('tenant_id', '?')}")
        print(f"  Generated:       {manifest.get('generated_at_utc', '?')}")

    metrics_path = os.path.join(out_base, "telemetry_metrics.jsonl")
    if os.path.isfile(metrics_path):
        metrics = load_jsonl(metrics_path)
        metric_names: Dict[str, int] = {}
        for m in metrics:
            name = m.get("name", "unknown")
            metric_names[name] = metric_names.get(name, 0) + 1
        print(f"\nMetric Counts:")
        for name, count in sorted(metric_names.items()):
            print(f"  {name}: {count}")
    return 0


# ── Pipeline commands ─────────────────────────────────────────


def cmd_pipeline_submit(args: argparse.Namespace) -> int:
    """Submit a pipeline job via the query adapter (ad_collaboration path)."""
    import subprocess
    import tempfile

    query = {
        "schema": "query_template/v1",
        "query_type": "ad_collaboration",
        "caller": args.caller,
        "job_id": args.job_id or f"admin_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "ad_collaboration": {
            "server_filters": [{"field": f.split("=")[0], "value": f.split("=")[1]}
                               for f in args.server_filters] if args.server_filters else [],
            "client_filters": [{"field": f.split("=")[0], "value": f.split("=")[1]}
                               for f in args.client_filters] if args.client_filters else [],
            "join_key_field": args.join_key_field,
            "value_field": args.value_field,
            "value_mode": args.value_mode,
            "k_threshold": args.k,
            "rate_limit": args.n,
        },
    }
    query["correlation_id"] = query["job_id"]

    qf = os.path.join(args.out_base, "_admin_query.json")
    os.makedirs(args.out_base, exist_ok=True)
    with open(qf, "w", encoding="utf-8") as f:
        json.dump(query, f)

    cmd = [
        sys.executable,
        os.path.join(REPO_ROOT, "scripts", "query_adapter.py"),
        "submit",
        "--query-file", qf,
        "--out-base", args.out_base,
    ]
    if args.policy_config:
        cmd += ["--policy-config", args.policy_config]

    result = subprocess.run(cmd, capture_output=False)
    return result.returncode


# ── Main ──────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="Admin CLI for seccomp-privacy-platform")
    sub = ap.add_subparsers(dest="command")

    # job
    job_ap = sub.add_parser("job", help="Job management")
    job_sub = job_ap.add_subparsers(dest="subcommand")
    job_status_ap = job_sub.add_parser("status", help="Show job status")
    job_status_ap.add_argument("--out-base", required=True)
    job_status_ap.add_argument("--job-id", default="")
    job_list_ap = job_sub.add_parser("list", help="List jobs")
    job_list_ap.add_argument("--out-base", default="tmp")

    # audit
    audit_ap = sub.add_parser("audit", help="Audit chain operations")
    audit_sub = audit_ap.add_subparsers(dest="subcommand")
    audit_show_ap = audit_sub.add_parser("show", help="Show audit chain")
    audit_show_ap.add_argument("--out-base", required=True)
    audit_show_ap.add_argument("--format", choices=["summary", "json"], default="summary")
    audit_verify_ap = audit_sub.add_parser("verify", help="Verify audit seal")
    audit_verify_ap.add_argument("--out-base", required=True)

    # report
    report_ap = sub.add_parser("report", help="Public report operations")
    report_sub = report_ap.add_subparsers(dest="subcommand")
    report_public_ap = report_sub.add_parser("public", help="Show public report")
    report_public_ap.add_argument("--out-base", required=True)
    report_list_ap = report_sub.add_parser("list", help="List reports")
    report_list_ap.add_argument("--out-base", default="tmp")

    # catalog
    catalog_ap = sub.add_parser("catalog", help="Catalog operations")
    catalog_sub = catalog_ap.add_subparsers(dest="subcommand")
    catalog_list_ap = catalog_sub.add_parser("list", help="List catalog entries")
    catalog_list_ap.add_argument("--out-base", required=True)
    catalog_list_ap.add_argument("--entry-type", default="",
                                 help="Filter by entry type: dataset, job, artifact, public_report, policy_binding")
    catalog_list_ap.add_argument("--tenant-id", default="default_tenant")

    # runbook
    runbook_ap = sub.add_parser("runbook", help="Runbook operations")
    runbook_sub = runbook_ap.add_subparsers(dest="subcommand")
    runbook_gen_ap = runbook_sub.add_parser("generate", help="Generate runbook")
    runbook_gen_ap.add_argument("--out-base", required=True)
    runbook_gen_ap.add_argument("--job-id", default="")

    # telemetry
    telemetry_ap = sub.add_parser("telemetry", help="Telemetry operations")
    telemetry_sub = telemetry_ap.add_subparsers(dest="subcommand")
    telemetry_summary_ap = telemetry_sub.add_parser("summary", help="Show telemetry summary")
    telemetry_summary_ap.add_argument("--out-base", required=True)

    # pipeline (convenience wrapper)
    pipeline_ap = sub.add_parser("pipeline", help="Pipeline job submission")
    pipeline_sub = pipeline_ap.add_subparsers(dest="subcommand")
    pipeline_submit_ap = pipeline_sub.add_parser("submit", help="Submit a pipeline job")
    pipeline_submit_ap.add_argument("--out-base", required=True)
    pipeline_submit_ap.add_argument("--caller", default="admin_cli")
    pipeline_submit_ap.add_argument("--job-id", default="")
    pipeline_submit_ap.add_argument("--server-filters", nargs="*", default=[])
    pipeline_submit_ap.add_argument("--client-filters", nargs="*", default=[])
    pipeline_submit_ap.add_argument("--join-key-field", default="email")
    pipeline_submit_ap.add_argument("--value-field", default="amount")
    pipeline_submit_ap.add_argument("--value-mode", default="raw-int")
    pipeline_submit_ap.add_argument("--k", type=int, default=20)
    pipeline_submit_ap.add_argument("--n", type=int, default=5)
    pipeline_submit_ap.add_argument("--policy-config", default="")

    args = ap.parse_args()

    if args.command == "job" and args.subcommand == "status":
        return cmd_job_status(args)
    elif args.command == "job" and args.subcommand == "list":
        return cmd_job_list(args)
    elif args.command == "audit" and args.subcommand == "show":
        return cmd_audit_show(args)
    elif args.command == "audit" and args.subcommand == "verify":
        return cmd_audit_verify(args)
    elif args.command == "report" and args.subcommand == "public":
        return cmd_report_public(args)
    elif args.command == "report" and args.subcommand == "list":
        return cmd_report_list(args)
    elif args.command == "catalog" and args.subcommand == "list":
        return cmd_catalog_list(args)
    elif args.command == "runbook" and args.subcommand == "generate":
        return cmd_runbook_generate(args)
    elif args.command == "telemetry" and args.subcommand == "summary":
        return cmd_telemetry_summary(args)
    elif args.command == "pipeline" and args.subcommand == "submit":
        return cmd_pipeline_submit(args)
    else:
        ap.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
