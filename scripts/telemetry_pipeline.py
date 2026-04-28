#!/usr/bin/env python3
"""Telemetry pipeline: reads existing audit JSONL and pipeline outputs, generates OTLP-compatible text metrics.

Does NOT modify any module internals. All metrics are derived from existing audit artifacts.
No sensitive plaintext (join keys, token secrets, raw identifiers) is ever emitted.
"""

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


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


def load_json(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def safe_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        return str(val)
    return str(val)


class TelemetryCollector:
    def __init__(self, out_base: str, tenant_id: str = "default_tenant"):
        self.out_base = os.path.abspath(out_base)
        self.tenant_id = tenant_id
        self.metrics: List[Dict[str, Any]] = []
        self.alerts: List[Dict[str, Any]] = []
        self.job_ids: set = set()

    def collect(self) -> None:
        sse_audit_path = os.path.join(self.out_base, "sse_exports", "export_audit.jsonl")
        recovery_audit_path = os.path.join(self.out_base, "sse_exports", "record_recovery_service_audit.jsonl")
        bridge_audit_path = os.path.join(self.out_base, "bridge_job", "bridge_audit.jsonl")
        bridge_job_meta_path = os.path.join(self.out_base, "bridge_job", "job_meta.json")
        pjc_result_path = os.path.join(self.out_base, "a_psi_run", "attribution_result.json")
        public_report_path = os.path.join(self.out_base, "a_psi_run", "public_report.json")
        policy_audit_path = os.path.join(self.out_base, "a_psi_run", "audit_log.jsonl")
        key_access_audit_path = os.path.join(self.out_base, "key_access_audit.jsonl")
        audit_chain_path = os.path.join(self.out_base, "audit_chain.json")

        sse_records = load_jsonl(sse_audit_path)
        recovery_records = load_jsonl(recovery_audit_path)
        bridge_records = load_jsonl(bridge_audit_path)
        policy_records = load_jsonl(policy_audit_path)
        key_access_records = load_jsonl(key_access_audit_path)
        bridge_job_meta = load_json(bridge_job_meta_path)
        pjc_result = load_json(pjc_result_path)
        public_report = load_json(public_report_path)
        audit_chain = load_json(audit_chain_path)

        for r in sse_records:
            self.job_ids.add(r.get("correlation_id") or r.get("job_id", ""))

        self._collect_sse_metrics(sse_records)
        self._collect_recovery_metrics(recovery_records)
        self._collect_bridge_metrics(bridge_records, bridge_job_meta)
        self._collect_pjc_metrics(pjc_result)
        self._collect_policy_metrics(policy_records, public_report)
        self._collect_key_access_metrics(key_access_records)
        self._collect_audit_chain_metrics(audit_chain)

    def _emit_metric(self, name: str, value: float, dimensions: Dict[str, str],
                     metric_type: str = "gauge", unit: str = "") -> None:
        ts = utc_now_iso()
        dims = {k: safe_str(v) for k, v in dimensions.items() if v is not None}
        self.metrics.append({
            "name": name,
            "value": value,
            "type": metric_type,
            "unit": unit,
            "dimensions": dims,
            "timestamp_utc": ts,
        })

    def _collect_sse_metrics(self, records: List[Dict[str, Any]]) -> None:
        for r in records:
            caller = r.get("caller", "unknown")
            job_id = r.get("correlation_id") or r.get("job_id", "unknown")
            role = r.get("role", "unknown")
            decision = r.get("decision", "unknown")
            reason = r.get("reason_code", "unknown")
            candidate_source = r.get("candidate_source", "unknown")
            recovery_boundary = r.get("record_recovery_boundary") or "none"
            output_rows = r.get("output_rows") or 0
            input_rows = r.get("input_rows") or 0
            candidate_count = r.get("candidate_count") or 0

            base_dims = {
                "job_id": job_id,
                "correlation_id": job_id,
                "caller": caller,
                "tenant_id": self.tenant_id,
                "stage": "sse_export",
            }

            self._emit_metric("seccomp_job_total", 1, base_dims, "counter")
            self._emit_metric("seccomp_stage_row_count", input_rows,
                              {**base_dims, "row_type": "input"}, "gauge", "rows")
            self._emit_metric("seccomp_stage_row_count", output_rows,
                              {**base_dims, "row_type": "output"}, "gauge", "rows")
            self._emit_metric("seccomp_sse_candidate_count", candidate_count,
                              {**base_dims, "candidate_source": candidate_source},
                              "gauge", "candidates")
            self._emit_metric("seccomp_recovery_boundary_total", 1,
                              {**base_dims, "record_recovery_boundary": recovery_boundary},
                              "counter")

            if decision == "deny":
                self._emit_metric("seccomp_stage_deny_total", 1,
                                  {**base_dims, "reason_code": reason, "status": "deny"},
                                  "counter")

            if r.get("output_sha256"):
                self._emit_metric("seccomp_artifact_hash_total", 1,
                                  {**base_dims, "artifact": "sse_export_output"}, "counter")

    def _collect_recovery_metrics(self, records: List[Dict[str, Any]]) -> None:
        for r in records:
            job_id = r.get("correlation_id") or r.get("job_id", "unknown")
            caller = r.get("caller", "unknown")
            decision = r.get("decision", "unknown")
            reason = r.get("reason_code", "unknown")
            output_rows = r.get("output_rows") or 0
            input_rows = r.get("input_rows") or 0

            base_dims = {
                "job_id": job_id,
                "correlation_id": job_id,
                "caller": caller,
                "tenant_id": self.tenant_id,
                "stage": "record_recovery",
            }

            self._emit_metric("seccomp_stage_row_count", input_rows,
                              {**base_dims, "row_type": "input"}, "gauge", "rows")
            self._emit_metric("seccomp_stage_row_count", output_rows,
                              {**base_dims, "row_type": "output"}, "gauge", "rows")

            if decision == "deny":
                self._emit_metric("seccomp_stage_deny_total", 1,
                                  {**base_dims, "reason_code": reason, "status": "deny"},
                                  "counter")

    def _collect_bridge_metrics(self, records: List[Dict[str, Any]],
                                 job_meta: Optional[Dict[str, Any]]) -> None:
        for r in records:
            job_id = r.get("job_id", "unknown")
            decision = r.get("decision", "unknown")
            reason = r.get("reason_code", "unknown")
            token_src = r.get("token_secret_source", {}).get("kind", "unknown")

            base_dims = {
                "job_id": job_id,
                "correlation_id": r.get("correlation_id", job_id),
                "caller": "bridge",
                "tenant_id": self.tenant_id,
                "stage": "bridge",
                "token_secret_source_kind": token_src,
            }

            self._emit_metric("seccomp_job_total", 1, base_dims, "counter")

            if decision == "deny":
                self._emit_metric("seccomp_stage_deny_total", 1,
                                  {**base_dims, "reason_code": reason, "status": "deny"},
                                  "counter")

        if job_meta:
            input_sizes = job_meta.get("input_sizes", {})
            for key, val in input_sizes.items():
                if isinstance(val, (int, float)):
                    self._emit_metric("seccomp_stage_row_count", float(val),
                                      {"stage": "bridge", "input_size_key": key,
                                       "tenant_id": self.tenant_id}, "gauge", "rows")

    def _collect_pjc_metrics(self, pjc_result: Optional[Dict[str, Any]]) -> None:
        if not pjc_result:
            return
        job_id = pjc_result.get("correlation_id") or pjc_result.get("job_id", "unknown")
        isect_size = pjc_result.get("intersection_size")
        isect_sum = pjc_result.get("intersection_sum")

        base_dims = {
            "job_id": job_id,
            "correlation_id": job_id,
            "tenant_id": self.tenant_id,
            "stage": "pjc",
        }

        if isect_size is not None:
            self._emit_metric("seccomp_pjc_intersection_size", float(isect_size),
                              base_dims, "gauge", "records")
        if isect_sum is not None:
            self._emit_metric("seccomp_pjc_intersection_sum", float(isect_sum),
                              base_dims, "gauge", "value")

    def _collect_policy_metrics(self, records: List[Dict[str, Any]],
                                 public_report: Optional[Dict[str, Any]]) -> None:
        for r in records:
            job_id = r.get("correlation_id") or r.get("job_id", "unknown")
            caller = r.get("caller", "unknown")
            decision = r.get("decision", "unknown")
            reason = r.get("reason_code", "unknown")
            threshold_k = r.get("threshold_k", 0)
            rate_used = r.get("rate_limit_used", 0)
            rate_max = r.get("rate_limit_max", 0)

            base_dims = {
                "job_id": job_id,
                "correlation_id": job_id,
                "caller": caller,
                "tenant_id": self.tenant_id,
                "stage": "policy_release",
            }

            self._emit_metric("seccomp_job_total", 1, base_dims, "counter")
            self._emit_metric("seccomp_release_decision_total", 1,
                              {**base_dims, "released": str(decision == "allow"),
                               "reason_code": reason}, "counter")
            self._emit_metric("seccomp_threshold_k", float(threshold_k),
                              base_dims, "gauge", "records")
            self._emit_metric("seccomp_rate_limit_used", float(rate_used),
                              base_dims, "gauge", "tokens")

            if r.get("canonical_query_signature"):
                self._emit_metric("seccomp_duplicate_query_check_total", 1,
                                  base_dims, "counter")

            if decision == "deny":
                self._emit_metric("seccomp_stage_deny_total", 1,
                                  {**base_dims, "reason_code": reason, "status": "deny"},
                                  "counter")

        if public_report:
            job_id = public_report.get("correlation_id") or public_report.get("job_id", "unknown")
            released = public_report.get("released", False)
            base_dims = {
                "job_id": job_id,
                "tenant_id": self.tenant_id,
                "stage": "public_report",
            }
            self._emit_metric("seccomp_release_decision_total", 1,
                              {**base_dims, "released": str(released),
                               "reason_code": public_report.get("reason_code", "unknown")},
                              "counter")

    def _collect_key_access_metrics(self, records: List[Dict[str, Any]]) -> None:
        for r in records:
            job_id = r.get("correlation_id") or r.get("job_id", "unknown")
            base_dims = {
                "job_id": job_id,
                "tenant_id": self.tenant_id,
                "stage": "key_access",
            }
            self._emit_metric("seccomp_key_access_total", 1, base_dims, "counter")

    def _collect_audit_chain_metrics(self, audit_chain: Optional[Dict[str, Any]]) -> None:
        if not audit_chain:
            return
        job_id = audit_chain.get("job_id", "unknown")
        counts = audit_chain.get("counts", {})
        base_dims = {"job_id": job_id, "tenant_id": self.tenant_id}
        for key, val in counts.items():
            if isinstance(val, (int, float)):
                self._emit_metric("seccomp_audit_record_count", float(val),
                                  {**base_dims, "audit_type": key}, "gauge", "records")
        artifacts = audit_chain.get("artifacts", {})
        for key, val in artifacts.items():
            self._emit_metric("seccomp_artifact_hash_total", 1 if val else 0,
                              {**base_dims, "artifact": key}, "gauge")

    def export_otlp_text(self) -> str:
        """Export metrics as OTLP-compatible text (newline-delimited JSON)."""
        lines = []
        for m in self.metrics:
            lines.append(json.dumps(m, ensure_ascii=False))
        return "\n".join(lines) + ("\n" if lines else "")

    def export_prometheus_text(self) -> str:
        """Export a Prometheus-style text representation (best-effort)."""
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for m in self.metrics:
            grouped[m["name"]].append(m)

        lines = []
        for name, entries in sorted(grouped.items()):
            lines.append(f"# HELP {name} {name}")
            lines.append(f"# TYPE {name} gauge")
            for e in entries:
                dims = ",".join(f'{k}="{v}"' for k, v in sorted(e["dimensions"].items()))
                label_part = f"{{{dims}}}" if dims else ""
                lines.append(f"{name}{label_part} {e['value']} {int(datetime.now().timestamp() * 1000)}")
        return "\n".join(lines) + "\n"

    def generate_alerts(self) -> List[Dict[str, Any]]:
        """Generate alerts based on collected metrics."""
        if not self.alerts:
            self._check_alerts()
        return self.alerts

    def _check_alerts(self) -> None:
        deny_count = sum(1 for m in self.metrics if m["name"] == "seccomp_stage_deny_total")
        job_count = sum(1 for m in self.metrics if m["name"] == "seccomp_job_total")
        if job_count > 0 and deny_count / job_count > 0.5:
            self.alerts.append({
                "alert": "HighStageDenyRate",
                "severity": "warning",
                "message": f"Deny rate {deny_count}/{job_count} exceeds threshold",
                "timestamp_utc": utc_now_iso(),
            })

        for m in self.metrics:
            if m["name"] == "seccomp_stage_duration_ms" and m["value"] > 60000:
                self.alerts.append({
                    "alert": "StageDurationHigh",
                    "severity": "warning",
                    "message": f"Stage {m['dimensions'].get('stage', 'unknown')} duration {m['value']}ms exceeds 60s",
                    "timestamp_utc": utc_now_iso(),
                })

    def write_manifest(self) -> Dict[str, Any]:
        return {
            "schema": "telemetry_manifest/v1",
            "generated_at_utc": utc_now_iso(),
            "source_dir": self.out_base,
            "tenant_id": self.tenant_id,
            "job_count": len(self.job_ids),
            "job_ids": sorted(self.job_ids),
            "metric_count": len(self.metrics),
            "alert_count": len(self.generate_alerts()),
        }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate OTLP-compatible telemetry from existing pipeline audit outputs."
    )
    ap.add_argument("--out-base", required=True,
                    help="Pipeline output directory containing sse_exports/, bridge_job/, a_psi_run/")
    ap.add_argument("--tenant-id", default="default_tenant",
                    help="Tenant identifier for metric dimensions")
    ap.add_argument("--format", choices=["otlp-jsonl", "prometheus"], default="otlp-jsonl",
                    help="Output format: otlp-jsonl (default) or prometheus")
    ap.add_argument("--out", default="",
                    help="Output path; defaults to <out-base>/telemetry_metrics.jsonl")
    ap.add_argument("--manifest-out", default="",
                    help="Manifest output path; defaults to <out-base>/telemetry_manifest.json")
    args = ap.parse_args()

    if not os.path.isdir(args.out_base):
        print(f"[ERROR] out-base directory not found: {args.out_base}", file=sys.stderr)
        return 1

    collector = TelemetryCollector(args.out_base, args.tenant_id)
    try:
        collector.collect()
    except Exception as e:
        print(f"[ERROR] telemetry collection failed: {e}", file=sys.stderr)
        return 1

    out_path = args.out or os.path.join(args.out_base, f"telemetry_metrics.{'jsonl' if args.format == 'otlp-jsonl' else 'txt'}")
    manifest_path = args.manifest_out or os.path.join(args.out_base, "telemetry_manifest.json")

    if args.format == "prometheus":
        output = collector.export_prometheus_text()
    else:
        output = collector.export_otlp_text()

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output)

    manifest = collector.write_manifest()
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"[ok] telemetry metrics ({len(collector.metrics)} records): {os.path.abspath(out_path)}")
    print(f"[ok] telemetry manifest: {os.path.abspath(manifest_path)}")
    if collector.alerts:
        print(f"[warn] {len(collector.alerts)} alert(s) triggered:")
        for a in collector.alerts:
            print(f"  [{a['severity']}] {a['alert']}: {a['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
