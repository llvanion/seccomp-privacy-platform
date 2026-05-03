# Code Review — Step 9: Sidecar Exporters

**Scope:** `scripts/export_observability_events.py`, `scripts/export_catalog_lineage.py`

---

## 1. Purpose

Both exporters derive structured sidecar artifacts from an existing `audit_chain.json` **without modifying the main pipeline**. Neither script stores any new files during a pipeline run; they are invoked post-run on demand or by the audit/public-report HTTP adapter.

| Exporter | Output schema | What it produces |
|---|---|---|
| `export_observability_events.py` | `pipeline_observability/v1` | Per-stage timing + status events, including derived handoff and exposure events |
| `export_catalog_lineage.py` | `catalog_lineage/v1` | Dataset/service/artifact graph nodes and directed lineage edges |

---

## 2. `export_observability_events.py`

### 2.1 Base Scope Extraction

Both exporters start with `base_scope(chain)`, which walks all stage audit lists to find the first non-empty value for `caller`, `tenant_id`, `dataset_id`, and `service_id`. This allows the scope fields to be populated even when some stages' audit records do not carry them directly.

### 2.2 Stage Events

One event is emitted per audit record in each stage, using `status_from_decision`:

```python
def status_from_decision(decision, *, exit_code=None, released=None) -> str:
    if exit_code not in (None, 0): return "error"
    if decision == "allow":       return "ok"
    if decision == "deny":        return "error"
    if released is True:          return "ok"
    if released is False:         return "error"
    return "unknown"
```

Stage event fields: `stage`, `status`, `ts_utc`, `role`, `decision`, `reason_code`, `duration_ms`, `row_count`, `artifact_sha256`, `source_event`.

For the bridge stage, `ts_utc` is derived from `ts_unix_ms` (bridge audit stores a Unix epoch millisecond timestamp, not ISO8601):
```python
if isinstance(record.get("ts_unix_ms"), int):
    ts_utc = datetime.fromtimestamp(record["ts_unix_ms"] / 1000, timezone.utc).isoformat()...
```

For the policy release stage, `row_count` is derived from `intersection_size` inside `parsed_metrics`:
```python
row_count = first_non_empty(metrics.get("intersection_size"), metrics.get("conversions"))
```

### 2.3 Derived Handoff Cleanup Events

`handoff_cleanup_events` sources from `mainline_contract_check/v1` inside the audit chain, emitting one event per role (`server`, `client`):

| cleanup_status | mainline_status | derived event status |
|---|---|---|
| `cleaned` | any | `ok` |
| `removed` | any | `ok` |
| `retained` | `ok` | `ok` (authorized compatibility mode) |
| `retained` | other | `error` |
| `missing_output_file` | any | `error` |

This makes retention of handoff files visible as a pipeline-level observability concern, not just a static audit field.

### 2.4 Derived Handoff Exposure Assessment Events

`handoff_exposure_assessment_events` emits:
1. One overall event with `stage="handoff_exposure_assessment"` and `reason_code` set to the overall `plaintext_exposure_risk`.
2. Two per-role events (server/client) with the individual role exposure risk.

Risk mapping to event status:
- `none` / `low` → `ok`
- `elevated` → `error`
- anything else → `unknown`

This surfaces the plaintext exposure risk directly in the observability stream without consumers needing to re-read the mainline contract JSON.

### 2.5 Service Audit Consistency Events

`service_audit_consistency_events` emits one event per role. For roles that used a service boundary (i.e. `record_recovery_boundary in {"service_socket", "service_http"}`), it looks up findings by kind:
- `missing_<role>_service_audit` → error
- `<role>_service_*` prefix → error
- `missing_service_audit`, `service_transport_mismatch` (global) → error
- No matching findings → ok

For roles that did not use a service boundary: `reason_code="not_applicable"`, `status="ok"`.

### 2.6 Output Ordering

Final events list order:
1. SSE export events (per role, per audit record)
2. Record recovery service events
3. Bridge events
4. PJC events
5. Policy release events
6. Handoff cleanup events (derived)
7. Handoff exposure assessment events (derived)
8. Service audit consistency events (derived)

---

## 3. `export_catalog_lineage.py`

### 3.1 Graph Structure

The catalog lineage output is a graph with four node types and typed edges:

| Node type | ID scheme | Source |
|---|---|---|
| `dataset` | `dataset:<tenant_id>:<dataset_id>` | SSE export audit, scope |
| `service` | `service:<service_id>` | Recovery service audit |
| `job` | `job:<job_id>` | audit_chain.json |
| `artifact` | `artifact:<stage>:<kind>:<sha256[:16]>` | Per-stage audit records |

Edges connect artifacts across stages, e.g.:
- `(sse_export artifact) → produces → (job)`
- `(bridge artifact) → consumes → (sse_export artifact)`
- `(job) → uses → (service)`

### 3.2 Path Redaction

All artifact `path` fields are redacted by default (`include_paths=False`). When an artifact lacks a SHA-256 (e.g. for FIFO-mode exports), `path_included=False` is recorded instead. The `--include-paths` CLI flag enables full path output — this is intentionally not the default.

```python
def add_artifact(*, kind, stage, ..., path=None, sha256=None, ...):
    item = {...}
    if include_paths:
        item["path"] = path
    else:
        item["path_included"] = False
```

**Observation:** Path redaction prevents file system layout information from propagating into catalog consumers, which is correct. The SHA-256 still uniquely identifies the artifact for verification purposes.

### 3.3 Duplicate Suppression

The `put_unique` helper merges catalog items by ID. If an artifact ID already exists, only null/empty fields are updated:
```python
def put_unique(items, item):
    existing = items.get(str(item["id"]))
    if existing is None:
        items[str(item_id)] = item
        return
    for key, value in item.items():
        if existing.get(key) in (None, "", []) and value not in (None, "", []):
            existing[key] = value
```

This prevents duplicate nodes when multiple audit records reference the same artifact (e.g. bridge audit and the SSE export audit both reference the same output path/hash).

### 3.4 Mainline Contract Summary in Catalog

`summarize_mainline_contract` (from `archive_audit_bundle.py`) is embedded in the catalog output. This allows catalog/lineage consumers to see handoff mode, cleanup status, and per-role service audit consistency verdicts in the same payload as the lineage graph, without reopening the full mainline contract JSON.

### 3.5 Release Summary

`release_summary` derives the job's release status from the public report and the last policy audit record:

```python
released = public_report.get("released")
if released is True:   status = "released"
elif released is False: status = "denied"
else:                   status = first_non_empty(latest_policy.get("decision"), "imported")
```

This three-way distinction (released / denied / imported-without-release-info) allows the catalog to correctly represent both completed runs and partially-imported historical runs.

---

## 4. Identified Gaps / Observations

| Item | Severity | Note |
|---|---|---|
| Both exporters recompute `base_scope` independently | Low | Shared `base_scope` implementation could be extracted; current duplication is minor |
| `handoff_cleanup_events` treats `retained` + `mainline_status=ok` as `ok` | Informational | Correct per the design (authorized compatibility mode), but auditors should still see the `reason_code="retained"` |
| Artifact IDs for SHA-256-less artifacts include a sequential index | Low | Index-based IDs are not stable across re-runs; if the same artifact appears in different order, IDs differ |
| `put_unique` first-write-wins for non-null fields | Low | If two audit records disagree on the same field, the first record's value is kept; no conflict detection |
| Path redaction is global, not per-field | Low | `output_sha256` is still included, which is sufficient for integrity verification |
| Bridge `ts_unix_ms` conversion is the only stage that needs epoch-to-ISO conversion | Informational | All other stages record ISO8601 directly in their audit records; bridge is the exception because Rust's `SystemTime` is easier to serialize as epoch |

---

## 5. Summary

The sidecar exporters are cleanly designed read-only consumers of `audit_chain.json`. They correctly derive higher-level observability signals (handoff cleanup, exposure risk, service consistency) that would be expensive for each downstream consumer to recompute from the raw audit data. Path redaction is correctly on by default. The catalog graph structure is sound; the main engineering limitation is that artifact IDs for FIFO-mode artifacts (no SHA-256) include a sequential index that is not stable across re-invocations.
