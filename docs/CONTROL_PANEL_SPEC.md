# Control Panel Spec — Dashboard → Job Control Panel

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

## 4. Three New Blocks

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
