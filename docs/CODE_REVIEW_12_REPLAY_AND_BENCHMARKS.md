# Code Review — Step 12: Replay Scripts and Benchmark Suite

**Scope:** `scripts/verify_pipeline_replay.sh`, `scripts/verify_fifo_handoff_replay.sh`, `scripts/benchmark_pipeline.py`, benchmark architecture

---

## 1. Replay Scripts — CI Correctness Guards

Both replay scripts share the same structure: they run the pipeline against checked-in example data in a fresh temp directory, then assert the result fields precisely. They are distinct from benchmarks — they exist to catch regressions, not to measure performance.

### 1.1 HOME Isolation

```bash
REPLAY_HOME="$(mktemp -d /tmp/seccomp_replay.XXXXXX)/home"
HOME="$REPLAY_HOME" RUSTUP_HOME="..." CARGO_HOME="..." bash run_sse_bridge_pipeline.sh ...
```

Both scripts redirect `HOME` to a fresh temp directory before running the pipeline. This prevents the pipeline from reading or writing any state from the developer's home directory (e.g. `~/.cargo`, `~/.config`). Cargo home and rustup home are forwarded from the original environment so the build doesn't download all of Rust tooling on every replay run.

The temp directory is cleaned up in a `trap cleanup EXIT` handler unless `--keep-out-dir` is passed.

### 1.2 `verify_pipeline_replay.sh` — File-Mode Assertions

After the pipeline completes, the script checks seven distinct assertions:

| Assertion | Field | Expected value |
|---|---|---|
| Intersection size | `public_report.details.intersection_size` | `2` |
| Intersection sum | `public_report.details.intersection_sum_raw` | `425` |
| Server handoff status | `mainline_contract_check.handoff_cleanup.server.status` | `cleaned` |
| Client handoff status | `mainline_contract_check.handoff_cleanup.client.status` | `cleaned` |
| No retention reason | `mainline_contract_check.handoff_cleanup.*.retention_reason` | empty |
| Handoff mode | `mainline_contract_check.handoff_mode` | `file` |
| Exposure risk | `mainline_contract_check.handoff_exposure_assessment.plaintext_exposure_risk` | `low` |

The `intersection_sum_raw` field is checked rather than `intersection_sum` — this is important because `intersection_sum` may be formatted as a EUR string when `value_mode=amount`, while `intersection_sum_raw` always holds the raw integer.

The exposure risk assertion (`expected=low`) is notable: it means a change that elevates the default file-mode handoff from `low` to `elevated` exposure will break this CI gate. This is the intended behavior.

### 1.3 `verify_fifo_handoff_replay.sh` — FIFO-Mode Assertions

The FIFO replay adds three assertions specific to FIFO mode:

| Assertion | Field | Expected value |
|---|---|---|
| SSE export output type (server) | `sse_export_audit[role=server].output_file_type` | `fifo` |
| SSE export output type (client) | `sse_export_audit[role=client].output_file_type` | `fifo` |
| Server CSV absent after run | `sse_exports/server.csv` existence | must not exist |
| Client CSV absent after run | `sse_exports/client.csv` existence | must not exist |
| Server handoff status | `mainline_contract_check.handoff_cleanup.server.status` | `removed` |
| Client handoff status | `mainline_contract_check.handoff_cleanup.client.status` | `removed` |

The `removed` (as opposed to `cleaned`) status is the correct designation for FIFO mode: a FIFO pipe is never written to disk, so the cleanup status is "removed by design" rather than "cleaned after bridge ingestion".

**Observation:** The SSE export audit field check (`output_file_type=fifo`) requires reading JSONL lines from the audit file to find the per-role records. The script does this with inline `python3 -c` calls — these are short, but they add script dependencies on Python being in PATH. The rest of the smoke suite refactored these to use `runtime_service_helpers.py`, but these replay scripts have not been migrated.

---

## 2. `benchmark_pipeline.py` — Pipeline Benchmark Structure

### 2.1 Three Modes

```python
MODES = ("file_handoff", "file_handoff_retained", "fifo_handoff")
```

Each mode exercises a distinct pipeline configuration:
- `file_handoff`: default cleanup-after-bridge behavior.
- `file_handoff_retained`: `--keep-sse-export-handoff-files --handoff-retention-reason benchmark_file_handoff_retained`.
- `fifo_handoff`: `--sse-export-handoff-mode fifo`.

### 2.2 `validate_completed_run` — Post-Run Assertion Logic

After each pipeline invocation, `validate_completed_run` performs a comprehensive correctness check before recording the timing:

1. **Correctness check:** `intersection_size == 2` and `intersection_sum == 425`.

2. **Embedded mainline contract consistency:**
```python
embedded = audit_chain.get("mainline_contract_check")
if embedded != mainline_contract_check:
    raise RuntimeError("audit chain embedded mainline contract check diverges from sidecar")
```
The benchmark verifies that the `mainline_contract_check.json` file and the copy embedded inside `audit_chain.json` are bit-for-bit identical. If they diverge, the benchmark fails — this catches a class of bug where the audit chain builder embeds a stale or partial mainline contract check.

3. **Per-mode handoff cleanup verification:**

| Mode | Expected `handoff_cleanup.*.status` | Expected `exists_after_run` | Expected `retention_reason` |
|---|---|---|---|
| `file_handoff` | `cleaned` | `False` | `None` |
| `file_handoff_retained` | `retained` | `True` | `benchmark_file_handoff_retained` |
| `fifo_handoff` | `removed` | `False` | `None` |

The benchmark enforces all three fields per role (server, client), not just the status string. This prevents a scenario where `status=retained` is recorded but `exists_after_run=False` (file was retained in status but deleted in reality).

### 2.3 Statistics

```python
def summarize(results):
    durations = [item["duration_ms"] for item in results if item.get("exit_code") == 0]
    return {
        "min": ..., "mean": ..., "p50": ..., "p95": ..., "max": ...
    }
```

The benchmark runs `--iterations N` invocations per mode (default typically 1 for CI, configurable for manual benchmarking) and computes min/mean/p50/p95/max over successful iterations. Failed iterations are counted but not included in timing statistics.

The `percentile` function uses linear interpolation between adjacent sorted values rather than ceiling/floor, giving smoother percentile estimates for small sample sizes.

### 2.4 Benchmark Output Schema

All benchmark scripts emit results validated against their respective schemas (`pipeline_benchmark/v1`, `live_sse_benchmark/v1`, etc.). The schemas are frozen in `config/schema_backcompat_baseline.json`, so any benchmark output field removal is caught by the CI backcompat check.

---

## 3. Benchmark Architecture — Common Patterns

All nine benchmark scripts (`benchmark_pipeline.py`, `benchmark_live_sse_demo.py`, `benchmark_pjc.py`, `benchmark_read_adapters.py`, `benchmark_record_recovery.py`, `benchmark_audit_bundle.py`, `benchmark_query_workflow.py`, `benchmark_platform_health.py`, `benchmark_derived_views.py`) share:

- **Correctness-then-timing:** Run the operation, assert correctness, then record timing. Timing is never recorded for a failed/incorrect run.
- **Schema-validated output:** Each benchmark emits a schema-versioned JSON report validated by `validate_json_contract.py`.
- **Per-mode coverage:** Most benchmarks cover multiple modes (file/fifo/retained for pipeline, Unix socket/HTTP for recovery, dry-run/execute for workflow, etc.) to ensure no mode silently breaks while timing regresses.
- **Synthetic fixtures:** Read-adapter, audit-bundle, and derived-views benchmarks build synthetic completed-run fixtures rather than requiring a live pipeline run, making them fast enough to include in default contract smoke.

### 3.1 Contract Smoke Semantic Assertions

`scripts/check_benchmark_smoke_reports.py` goes beyond schema validation and checks semantic invariants:

- Query workflow benchmark: dry-run mode must be covered.
- Read adapter benchmark: job and jobs-list modes must carry `mainline_contract_summary`; entity modes must carry the `permission_summary` role matrix.
- Record recovery benchmark: Unix-socket and HTTP health/recover operations must both appear.
- Audit bundle benchmark: verify, archive-index verify, and restore modes must all be covered; anchor-chain invariants must hold.
- Platform health benchmark: all component names from the CLI-only fallback must appear.
- Derived views benchmark: `handoff_exposure_assessment` must appear in `EXPECTED_STAGES`.

These semantic checks catch the scenario where a benchmark runs and passes schema validation but silently skips a mode — which would happen if the benchmark's test fixture was built without that mode's data.

---

## 4. Identified Gaps / Observations

| Item | Severity | Note |
|---|---|---|
| Replay scripts use inline `python3 -c` for JSON field extraction | Low | Should use `runtime_service_helpers.py read-json-field` for consistency |
| `benchmark_pipeline.py` requires `BRIDGE_TOKEN_SECRET` env var when `--production-mode` is used | Informational | Default benchmark mode is local compatibility coverage; production benchmark runs must also provide `--pjc-resource-limits` and omit retained-file handoff |
| Benchmark iterations default is 1 for most benchmarks | Low | Single-iteration timing is noisy; manual benchmarking requires explicit `--iterations N` |
| `percentile` uses linear interpolation | Informational | Correct but less intuitive than nearest-rank; both are valid for small samples |
| `file_handoff_retained` mode embeds a hardcoded `retention_reason` string | Low | The string `"benchmark_file_handoff_retained"` is asserted in `validate_completed_run`; changing either the benchmark command or the assertion without updating both would fail silently |

---

## 5. Summary

The replay scripts provide a strong correctness gate: they assert not just the intersection result but also the handoff cleanup state and exposure risk level. The CI integration means any regression in these contract fields fails the build. The pipeline benchmark extends this with three-mode coverage (file/retained/FIFO) and a precise per-mode assertion model that validates the `mainline_contract_check.json` content, not just the intersection result. The nine benchmark scripts together cover every major read and write surface, and the semantic assertion layer in `check_benchmark_smoke_reports.py` prevents mode-coverage drift.
