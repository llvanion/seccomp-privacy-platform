#!/usr/bin/env python3
"""Generate a markdown runbook from existing pipeline outputs.

Reads audit_chain.json and other pipeline artifacts to produce a human-readable
runbook describing the stage-by-stage health of a pipeline run.

No sensitive plaintext is included in the runbook.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


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


def stage_icon(decision: str) -> str:
    return "PASS" if decision == "allow" else "FAIL"


def human_bytes(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b / (1024 * 1024):.1f} MB"


def file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def build_runbook(out_base: str, job_id: str) -> str:
    out_base = os.path.abspath(out_base)
    audit_chain = load_json(os.path.join(out_base, "audit_chain.json"))
    audit_seal = load_json(os.path.join(out_base, "audit_chain.seal.json"))
    public_report = load_json(os.path.join(out_base, "a_psi_run", "public_report.json"))
    pjc_result = load_json(os.path.join(out_base, "a_psi_run", "attribution_result.json"))
    bridge_meta = load_json(os.path.join(out_base, "bridge_job", "job_meta.json"))
    bridge_audit = load_jsonl(os.path.join(out_base, "bridge_job", "bridge_audit.jsonl"))
    sse_audit = load_jsonl(os.path.join(out_base, "sse_exports", "export_audit.jsonl"))
    recovery_audit = load_jsonl(os.path.join(out_base, "sse_exports", "record_recovery_service_audit.jsonl"))
    policy_audit = load_jsonl(os.path.join(out_base, "a_psi_run", "audit_log.jsonl"))

    lines: List[str] = []
    lines.append(f"# Pipeline Runbook — {job_id}")
    lines.append(f"")
    lines.append(f"**Generated**: {utc_now_iso()}  ")
    lines.append(f"**Output directory**: `{out_base}`  ")
    lines.append(f"")

    # Summary
    lines.append("## Summary")
    lines.append("")
    if public_report:
        released = "RELEASED" if public_report.get("released") else "WITHHELD"
        lines.append(f"| Field | Value |")
        lines.append(f"|-------|-------|")
        lines.append(f"| Job ID | `{public_report.get('job_id', job_id)}` |")
        lines.append(f"| Caller | `{public_report.get('caller', 'unknown')}` |")
        lines.append(f"| Release decision | **{released}** |")
        lines.append(f"| Reason | {public_report.get('reason', 'unknown')} ({public_report.get('reason_code', '')}) |")
        lines.append(f"| K threshold | {public_report.get('k_threshold', '?')} |")
        lines.append(f"| Rate limit | {public_report.get('rate_limit_used', '?')}/{public_report.get('rate_limit_max', '?')} |")
        lines.append(f"")
    if pjc_result:
        lines.append(f"| PJC Metric | Value |")
        lines.append(f"|------------|-------|")
        lines.append(f"| Intersection size | {pjc_result.get('intersection_size', '?')} |")
        lines.append(f"| Intersection sum | {pjc_result.get('intersection_sum', '?')} |")
        lines.append(f"")

    # Stage-by-stage
    lines.append("## Stage Details")
    lines.append("")

    # SSE Export
    lines.append("### 1. SSE Export")
    lines.append("")
    if sse_audit:
        for r in sse_audit:
            decision = r.get("decision", "unknown")
            lines.append(f"- **{stage_icon(decision)}** role=`{r.get('role','?')}` caller=`{r.get('caller','?')}`")
            lines.append(f"  - Decision: `{decision}` ({r.get('reason_code','?')})")
            lines.append(f"  - Input rows: {r.get('input_rows','?')}, Output rows: {r.get('output_rows','?')}")
            lines.append(f"  - Candidate source: `{r.get('candidate_source','?')}`")
            if r.get("candidate_count"):
                lines.append(f"  - Candidate count: {r.get('candidate_count')}")
            lines.append(f"  - Output hash: `{r.get('output_sha256','?')}`")
            lines.append(f"  - Recovery boundary: `{r.get('record_recovery_boundary','none')}`")
            lines.append(f"")
    else:
        lines.append("No SSE export audit records found.")
        lines.append("")

    # Record Recovery
    if recovery_audit:
        lines.append("### 2. Record Recovery Service")
        lines.append("")
        for r in recovery_audit:
            decision = r.get("decision", "unknown")
            lines.append(f"- **{stage_icon(decision)}** caller=`{r.get('caller','?')}`")
            lines.append(f"  - Decision: `{decision}` ({r.get('reason_code','?')})")
            lines.append(f"  - Input rows: {r.get('input_rows','?')}, Output rows: {r.get('output_rows','?')}")
            lines.append(f"  - Auth mode: `{r.get('auth_mode','?')}`")
            lines.append(f"  - Output hash: `{r.get('output_sha256','?')}`")
            lines.append(f"")

    # Bridge
    lines.append(f"### {3 if recovery_audit else 2}. Bridge Tokenization")
    lines.append("")
    if bridge_audit:
        for r in bridge_audit:
            decision = r.get("decision", "unknown")
            token_src = r.get("token_secret_source", {}).get("kind", "unknown")
            lines.append(f"- **{stage_icon(decision)}** token-source=`{token_src}`")
            lines.append(f"  - Job ID: `{r.get('job_id','?')}`")
            lines.append(f"  - Correlation ID: `{r.get('correlation_id','?')}`")
            lines.append(f"  - Server input type: `{r.get('server_input_file_type','?')}`")
            lines.append(f"  - Client input type: `{r.get('client_input_file_type','?')}`")
            lines.append(f"")
    if bridge_meta:
        lines.append(f"  - Token scheme: `{bridge_meta.get('bridge',{}).get('token_scheme','?')}`")
        lines.append(f"  - Token scope: `{bridge_meta.get('bridge',{}).get('token_scope','?')}`")
        lines.append(f"  - Token key version: `{bridge_meta.get('bridge',{}).get('token_key_version','?')}`")
        lines.append(f"  - Normalizer version: `{bridge_meta.get('bridge',{}).get('normalize_version','?')}`")
        lines.append(f"")

    # PJC
    lines.append(f"### {4 if recovery_audit else 3}. Private Join & Compute")
    lines.append("")
    if pjc_result:
        lines.append(f"- Intersection size: **{pjc_result.get('intersection_size','?')}**")
        lines.append(f"- Intersection sum: **{pjc_result.get('intersection_sum','?')}**")
        lines.append(f"")

    # Policy Release
    lines.append(f"### {5 if recovery_audit else 4}. Policy Release")
    lines.append("")
    if policy_audit:
        for r in policy_audit:
            decision = r.get("decision", "unknown")
            lines.append(f"- **{stage_icon(decision)}** {r.get('reason','?')} ({r.get('reason_code','?')})")
            lines.append(f"  - Threshold k: {r.get('threshold_k','?')}")
            lines.append(f"  - Rate limit: {r.get('rate_limit_used','?')}/{r.get('rate_limit_max','?')}")
            lines.append(f"  - Canonical query signature: `{r.get('canonical_query_signature','?')[:16]}...`")
            lines.append(f"  - PJC result hash: `{r.get('pjc_result_sha256','?')}`")
            lines.append(f"  - Release hash: `{r.get('release_sha256','?')}`")
            lines.append(f"")

    # Audit integrity
    lines.append("## Audit Integrity")
    lines.append("")
    if audit_chain:
        counts = audit_chain.get("counts", {})
        lines.append(f"| Audit Stream | Records |")
        lines.append(f"|-------------|---------|")
        lines.append(f"| SSE export | {counts.get('sse_export_audit_records', 0)} |")
        lines.append(f"| Record recovery | {counts.get('record_recovery_service_audit_records', 0)} |")
        lines.append(f"| Bridge | {counts.get('bridge_audit_records', 0)} |")
        lines.append(f"| Policy | {counts.get('policy_audit_records', 0)} |")
        lines.append(f"| Key access | {counts.get('key_access_audit_records', 0)} |")
        lines.append(f"")

        artifacts = audit_chain.get("artifacts", {})
        lines.append(f"| Artifact | SHA-256 |")
        lines.append(f"|----------|---------|")
        for name, sha in artifacts.items():
            lines.append(f"| {name} | `{sha or 'N/A'}` |")
        lines.append(f"")

    if audit_seal:
        lines.append(f"- Audit chain SHA-256: `{audit_seal.get('audit_chain_sha256','?')}`")
        if audit_seal.get("hmac_sha256"):
            lines.append(f"- HMAC signature: `{audit_seal['hmac_sha256'][:16]}...`")
            lines.append(f"- HMAC key env: `{audit_seal.get('hmac_key_env','?')}`")
        lines.append(f"")

    # Actions
    lines.append("## Actions")
    lines.append("")
    all_allowed = True
    for r in sse_audit:
        if r.get("decision") == "deny":
            all_allowed = False
            lines.append(f"- [ ] Investigate SSE export deny: `{r.get('reason_code','?')}` for role `{r.get('role','?')}`")
    for r in recovery_audit:
        if r.get("decision") == "deny":
            all_allowed = False
            lines.append(f"- [ ] Investigate recovery service deny: `{r.get('reason_code','?')}`")
    for r in bridge_audit:
        if r.get("decision") == "deny":
            all_allowed = False
            lines.append(f"- [ ] Investigate bridge deny: `{r.get('reason_code','?')}`")
    for r in policy_audit:
        if r.get("decision") == "deny":
            lines.append(f"- [ ] Review policy deny: `{r.get('reason_code','?')}` — may be expected (below k, rate limited)")

    if all_allowed and not policy_audit:
        lines.append("- [x] All stages allowed — no actions required")
    elif not any(r.get("decision") == "deny" for r in policy_audit):
        lines.append("- [x] No unexpected denies — review complete")

    lines.append("")
    lines.append(f"---")
    lines.append(f"*Runbook auto-generated by `scripts/generate_observability_runbook.py`*")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate a markdown runbook from pipeline audit outputs."
    )
    ap.add_argument("--out-base", required=True,
                    help="Pipeline output directory containing sse_exports/, bridge_job/, a_psi_run/")
    ap.add_argument("--job-id", default="",
                    help="Job ID; auto-detected from audit_chain.json if omitted")
    ap.add_argument("--out", default="",
                    help="Output markdown path; defaults to <out-base>/runbook.md")
    args = ap.parse_args()

    if not os.path.isdir(args.out_base):
        print(f"[ERROR] out-base directory not found: {args.out_base}", file=sys.stderr)
        return 1

    job_id = args.job_id
    if not job_id:
        audit_chain = load_json(os.path.join(args.out_base, "audit_chain.json"))
        if audit_chain:
            job_id = audit_chain.get("job_id", "unknown_job")
        else:
            job_id = "unknown_job"

    try:
        runbook = build_runbook(args.out_base, job_id)
    except Exception as e:
        print(f"[ERROR] runbook generation failed: {e}", file=sys.stderr)
        return 1

    out_path = args.out or os.path.join(args.out_base, "runbook.md")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(runbook)

    print(f"[ok] runbook written: {os.path.abspath(out_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
