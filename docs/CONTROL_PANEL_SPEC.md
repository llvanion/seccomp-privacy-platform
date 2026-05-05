# Control Panel Spec — PJC X-UI Control and Audit Center

This spec is the concrete design target for post-baseline operator work in [POST_BASELINE_ROADMAP.md](/home/llvanion/Desktop/seccomp-privacy-platform/docs/POST_BASELINE_ROADMAP.md), especially:

1. `B9`：job start/status/result transport contract
2. `B10`：live progress read path
3. `B11`：Web control shell baseline

Phase-1 implementation status (`2026-05-05`):

1. `scripts/serve_operator_dashboard.py` now exposes `POST /v1/jobs/start`, `GET /v1/jobs/{job_id}`, `GET /v1/jobs/{job_id}/result`
2. the embedded HTML now swaps `Job Setup` / `Live Progress` / `Result` by UI state and hides historical blocks during `running`
3. the first implementation is request-file centric: `POST /v1/jobs/start` currently accepts either an inline `query_workflow_request/v1` payload or a `request_file` + `overrides` body, instead of a fully expanded field-by-field CSV/TLS form
4. the UI is now explicitly presented as **`PJC X-UI`** rather than a generic dashboard: it is an admin-only loopback shell for PJC control and audit
5. the audit center now integrates SSE export audit, SSE recovery-service audit when present, wrapper sidecars, PJC/policy artifacts, and compact `mainline_contract_summary`
6. the shell now also exposes a first multi-run admin view:
   - recent-run discovery under `--history-root`
   - active-run switching without restarting the shell
   - `GET /v1/runs` + `POST /v1/runs/select`
7. the shell now also exposes a first durable-wrapper action:
   - `POST /v1/jobs/{job_id}/relaunch`
   - action is constrained by `workflow_retry_eligibility/v1`
   - current phase only supports request-file-backed runs, not `<inline>` submissions

That means this spec is now half design target, half implementation reference: the live transport and UI state machine exist, while the richer field-by-field setup form can still evolve later.

## 1. Problem: Overlap in the Current Layout

The current dashboard has seven panels that all read the **same completed run**.
Adding job control without a clear boundary creates three overlaps:

| Overlap | Panels involved |
|---------|----------------|
| Stage progress shown twice | `stage_timeline` (historical) + new live progress tracker |
| Job state shown twice | `workflow_status` card + new result card |
| Error counts shown twice | `failure_summary` + new live progress error states |

The fix: **one source of truth per concern, controlled by UI state.**

---

## 2. UI State Machine (single variable)

```
idle ──[Start Job]──► running ──[exit 0]──► completed
                          └───[exit ≠0]──► failed
completed / failed ──[Reset / New Job]──► idle
```

Every panel's visibility is a function of this one state.

---

## 3. Block Map — What Each Block Owns (no overlap)

### 3a. Permanent blocks (always visible)

| Block | Owns | Does NOT own |
|-------|------|--------------|
| **Header** | Overall status badge, job_id, last-refresh ts, countdown | No job control |
| **Alerts** | 4 alert conditions on the last completed run | Not live status during a run |
| **Platform Health** | Component reachability (certs, binaries, metadata DB) | Not stage-level status |

### 3b. Control-plane blocks (mutually exclusive — swap on state change)

| State | Visible block | Hidden block |
|-------|--------------|--------------|
| `idle` | **Job Setup form** | Live Progress, Result |
| `running` | **Live Progress** | Job Setup form, Result |
| `completed` | **Result card** | Job Setup form, Live Progress |
| `failed` | **Result card** (with error) | Job Setup form, Live Progress |

### 3c. History blocks (visible only when `idle`, `completed`, or `failed`)

These read sidecar files from the **last completed run**.
They are **hidden during `running`** to avoid showing stale data alongside live progress.

| Block | Owns | Hidden when |
|-------|------|-------------|
| **Stage Summary** | Per-stage ok/error counts from last run | `running` |
| **Stage Duration** | Timing stats from last run | `running` |
| **Release Outcomes** | Per-tenant policy release from last run | `running` |
| **Failure Summary** | Error events from last run | `running` |
| **Stage Timeline** | Chronological events from last run | `running` |

> **Why keep `workflow_status`?**
> Remove it. Its content (`state`, `recommended_action`) is now owned by the Result card.
> Keeping it alongside the Result card is the only remaining overlap to eliminate.

---

## 4. Four Operator Blocks

### Block A — Job Setup Form (`idle` only)

```
┌─ Start a Job ──────────────────────────────────────┐
│  server CSV  [_________________________________]    │
│  client CSV  [_________________________________]    │
│  job ID      [____________________] (auto-fill)    │
│                                                    │
│  ☐ TLS mode (cross-internet)                       │
│    remote host  [___________________]              │
│    cert dir     [___________________]              │
│                                                    │
│              [ ▶ Start Job ]                       │
└────────────────────────────────────────────────────┘
```

Owns: job configuration input and the `POST /v1/jobs/start` call.
Does NOT own: result display, progress display.

### Block B — Live Progress (`running` only)

```
┌─ Running — job_id: cross-internet-001 ─ 14s ──────┐
│  sse_export         ████████████  ok     0.12s    │
│  record_recovery    ████████████  ok     0.23s    │
│  bridge             ████████████  ok     0.56s    │
│  pjc                ░░░░░░░░░░░░  running…        │
│  policy_release     ────────────  waiting         │
└────────────────────────────────────────────────────┘
```

Owns: live stage states from `GET /v1/jobs/{job_id}`, elapsed time.
Does NOT own: final metrics, error details (those go in Result).
Does NOT duplicate: stage_timeline (which shows post-run history), stage_summary (which shows counts).

### Block C — Result Card (`completed` or `failed`)

```
┌─ Result — job_id: cross-internet-001 ─────────────┐
│  ✓ completed in 4.2s                              │  (or ✗ failed)
│                                                   │
│  intersection_size    2                           │
│  intersection_sum   425                           │
│  released           ✓  threshold_passed           │  (or ✗ below_k)
│                                                   │
│  [ View Full Report ]   [ Start New Job ]         │
└────────────────────────────────────────────────────┘
```

Owns: `intersection_size`, `intersection_sum`, `released`, `reason_code`, elapsed time.
Does NOT own: per-stage timing (Stage Duration block), per-stage errors (Failure Summary block).
Does NOT duplicate: workflow_status (removed).

### Block D — Audit Center (`always visible`, admin-only)

The web shell is now explicitly an admin surface, so SSE audit is a first-class block rather than something operators inspect by hand in `sse_exports/*.jsonl`.

Phase-1 ownership:

1. SSE export audit summary by role (`server` / `client`)
2. SSE record-recovery-service audit summary by role when the service boundary is used
3. artifact inventory across wrapper, SSE, bridge, PJC, policy, and audit-chain outputs
4. compact mainline contract summary:
   - `status`
   - `handoff_mode`
   - `handoff_cleanup`
   - `service_audit_consistency`

### Block E — Recent Runs (`always visible`, admin-only)

The shell now also owns a minimal multi-run surface:

1. scan a configurable history root for prior `query_workflow/status.json`
2. render recent runs with state, caller, tenant, receipts, and active marker
3. switch the active audit/control context to another completed run without restarting the server
4. block cross-run switching while another job is actively `running`

---

## 5. New Server Endpoints

### `POST /v1/jobs/start`

Request body:
```json
{
  "server_csv":   "/abs/path/server.csv",
  "client_csv":   "/abs/path/client.csv",
  "job_id":       "my-job-001",
  "tls_mode":     false,
  "server_host":  "",
  "cert_dir":     ""
}
```

Response (`202 Accepted`):
```json
{ "job_id": "my-job-001", "state": "running", "started_at_utc": "..." }
```

Error (`409 Conflict` if a job is already running):
```json
{ "error": "job_already_running", "job_id": "..." }
```

Server action: spawns `run_sse_bridge_pipeline.sh` (plain) or `run_pjc_server_tls.sh` (TLS) as a background subprocess. Stores PID + state in memory.

### `GET /v1/jobs/{job_id}`

Polls this endpoint every 2 seconds from the Live Progress block.

Response:
```json
{
  "job_id":      "my-job-001",
  "state":       "running",
  "elapsed_sec": 14.2,
  "stages": [
    { "name": "sse_export",      "status": "ok",      "duration_ms": 120 },
    { "name": "bridge",          "status": "ok",      "duration_ms": 560 },
    { "name": "pjc",             "status": "running", "duration_ms": null },
    { "name": "policy_release",  "status": "waiting", "duration_ms": null }
  ],
  "exit_code": null
}
```

Stage status values: `ok`, `error`, `running`, `waiting`.
Server derives stage states by tailing the live audit log written to `out_base/`.

### `GET /v1/jobs/{job_id}/result`

Called once when `GET /v1/jobs/{job_id}` returns `state=completed` or `state=failed`.

Response:
```json
{
  "job_id":            "my-job-001",
  "state":             "completed",
  "elapsed_sec":       4.2,
  "exit_code":         0,
  "intersection_size": 2,
  "intersection_sum":  425,
  "released":          true,
  "reason_code":       "threshold_passed",
  "out_base":          "/abs/path/to/run"
}
```

Server reads `attribution_result.json` and `public_report.json` from `out_base`.
Returns `404` if the run has not completed yet.

### `GET /v1/runs`

Returns a recent-run list derived from `query_workflow_status_list/v1` semantics.

Supported query params:

1. `limit`
2. `state`
3. `job_id`

### `POST /v1/runs/select`

Request body:

```json
{
  "out_base": "tmp/operator_dashboard_jobtest2"
}
```

Effect:

1. switches the shell's active `out_base`
2. reseeds the current terminal job snapshot from that run's `query_workflow/status.json`
3. rejects the switch with `409` if another job is currently `running`

### `POST /v1/jobs/{job_id}/relaunch`

Current phase-1 durable-wrapper semantics:

1. only allowed when the selected run is terminal and not currently `running`
2. action must match `recommended_action` from retry eligibility:
   - `retry`
   - `resubmit`
3. only supported when `submission_manifest.json` points at a real `request_file`
4. server auto-generates a fresh `job_id` and sibling `out_base` when the caller does not override them

---

## 6. Final Page Layout (by state)

### `idle`
```
[ Header ]
[ Alerts ]  [ Platform Health ]
[ Job Setup Form                                    ]
[ Stage Summary ]  [ Stage Duration ]  [ Release Outcomes ]
[ Failure Summary ]  (empty if no prior run)
[ Stage Timeline ]   (empty if no prior run)
```

### `running`
```
[ Header ]
[ Alerts ]  [ Platform Health ]
[ Live Progress                                     ]
(all history blocks hidden)
```

### `completed` or `failed`
```
[ Header ]
[ Alerts ]  [ Platform Health ]
[ Result Card                                       ]
[ Stage Summary ]  [ Stage Duration ]  [ Release Outcomes ]
[ Failure Summary ]
[ Stage Timeline ]
```

---

## 7. File Changes

| File | Change |
|------|--------|
| `scripts/serve_operator_dashboard.py` | Add 3 endpoints; add in-memory job state tracker; keep existing `/v1/dashboard` cache unchanged |
| HTML (embedded) | Remove `renderWorkflowStatus`; add `renderJobSetup`, `renderLiveProgress`, `renderResult`; gate history blocks on `appState !== 'running'` |
| No other files | The pipeline scripts are called as subprocesses — no changes to them |

---

## 8. What to Avoid

- Do not add stage-level details to the Result card — that belongs to Stage Duration / Failure Summary.
- Do not show the Job Setup form during `running` — it causes a second job to start on a double-click.
- Do not show history blocks during `running` — they show stale data from the previous run and contradict the live progress.
- Do not merge Live Progress with Stage Timeline — they serve different time windows (live vs historical).
- Do not put `intersection_size` / `intersection_sum` in the header bar — those belong in the Result card only.

---

## 9. Suggested Delivery Order

To keep this spec aligned with the post-baseline roadmap, implement it in this order:

1. `B9`：first freeze the server transport
   - `POST /v1/jobs/start`
   - `GET /v1/jobs/{job_id}`
   - `GET /v1/jobs/{job_id}/result`
2. `B10`：then make the live progress read path reliable
   - derive running state from live audit / sidecar artifacts
   - keep historical completed-run panels hidden during `running`
3. `B11`：only then wire the HTML shell
   - `idle -> running -> completed|failed` state machine
   - Job Setup / Live Progress / Result card block swap

This order matters because:

1. transport contract must exist before UI state can be trusted
2. live progress semantics must be correct before historical panels are gated off
3. the UI should consume stable control-plane responses, not invent its own filesystem rules
