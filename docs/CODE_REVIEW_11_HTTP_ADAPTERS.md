# Code Review — Step 11: Sidecar HTTP Adapters

**Scope:** `scripts/serve_metadata_api.py`, `scripts/serve_audit_query_api.py`, `scripts/serve_query_workflow_api.py`, `scripts/serve_platform_health_api.py`

---

## 1. Shared Architecture

All four adapters follow the same structure:

```
ThreadingHTTPServer subclass (state: db_path / out_base / auth_token / lifecycle files)
  └── BaseHTTPRequestHandler subclass
        ├── /healthz  — unauthenticated, reports {ok: true, auth_required: ...}
        └── /v1/...   — Bearer-token auth, returns {schema, method, path, result}
```

Common patterns across all four:
- `daemon_threads = True` on the server — worker threads do not block shutdown.
- `allow_reuse_address = True` — allows rapid restart after `SIGTERM` without waiting for `TIME_WAIT`.
- `log_message` is overridden to `return` — no per-request stdout logging (avoids log noise for sidecar tools).
- Auth is a plain bearer-token equality check — no HMAC, no expiry.
- SIGTERM / SIGINT handlers call `server.shutdown()` in a daemon thread, allowing graceful shutdown without deadlocking the main thread.
- `pid_file` and `ready_file` are written at startup and removed on graceful shutdown.

---

## 2. `serve_metadata_api.py` — SQLite Metadata Sidecar

### 2.1 Endpoints

| Endpoint | Method | Auth | Returns |
|---|---|---|---|
| `/healthz` | GET | No | `metadata_api_health/v1` |
| `/v1/jobs/:job_id` | GET | Yes | `metadata_api_response/v1` wrapping job detail |
| `/v1/jobs` | GET | Yes | `metadata_api_response/v1` wrapping jobs list |
| `/v1/entities/:entity` | GET | Yes | `metadata_api_response/v1` wrapping entity list |

### 2.2 Concurrency Model

Uses a `state_lock: threading.Lock()` on every database access:

```python
with self.server.state_lock:
    conn = connect_db(self.server.db_path)
    try:
        result = query_job_detail(conn, job_id=job_id, ...)
    finally:
        conn.close()
```

Every request creates and closes its own connection, serialized by the lock. This prevents concurrent write races on the SQLite file (SQLite supports multiple readers but not concurrent writers). For a read-only API over an imported DB, this is acceptable though conservative — WAL mode would allow concurrent readers.

### 2.3 Job Detail Routing

```python
if path.startswith("/v1/jobs/"):
    job_id = unquote(path[len("/v1/jobs/"):])
    result = query_job_detail(conn, job_id=job_id, ...)
elif path == "/v1/jobs":
    result = query_jobs(conn, caller=..., stage=..., ...)
elif path.startswith("/v1/entities/"):
    entity = unquote(path[len("/v1/entities/"):])
    result = query_entities(conn, entity=entity, ...)
```

URL decoding (`unquote`) handles job IDs that contain encoded characters.

---

## 3. `serve_audit_query_api.py` — Audit/Public-Report Adapter

### 3.1 Endpoints

| Endpoint | Method | Auth | Returns |
|---|---|---|---|
| `/healthz` | GET | No | Lists available result schemas |
| `/v1/public-report` | GET | Yes | `public_report/v2` |
| `/v1/audit-chain` | GET | Yes | `audit_chain/v1` |
| `/v1/observability` | GET | Yes | `pipeline_observability/v1` (derived on demand) |
| `/v1/catalog-lineage` | GET | Yes | `catalog_lineage/v1` (derived on demand); `?include_paths=true` for full paths |

### 3.2 Stateless Read-Only Design

The server stores only `out_base` and derives all paths from it. It has **no state lock** because it never writes and all reads are from JSON files (not SQLite). The sidecar exporters (`build_observability`, `build_catalog_lineage`) are called inline per request — there is no caching. For large audit chains this could be slow, but for the current prototype scale it is fine.

The `/healthz` response advertises the available result schemas, giving clients a way to discover the API surface without consulting documentation.

### 3.3 Startup Validation

The server validates that `out_base/audit_chain.json` and `out_base/a_psi_run/public_report.json` exist before starting:

```python
if not audit_chain_path.is_file():
    raise SystemExit(f"[ERROR] audit chain does not exist: {audit_chain_path}")
```

This prevents the server from starting in a state where all authenticated endpoints would immediately 500. It is the correct fail-fast behavior.

---

## 4. `serve_query_workflow_api.py` — Query Workflow Adapter

### 4.1 Endpoints

| Endpoint | Method | Auth | Returns |
|---|---|---|---|
| `/healthz` | GET | No | Reports `allow_execute` flag and `request_base_dir_default` |
| `/v1/query-workflows/dry-run` | POST | Yes | `query_workflow_api_response/v1` with dry-run manifest |
| `/v1/query-workflows/execute` | POST | Yes | Same, but only if `--allow-execute` was passed at startup |

### 4.2 Execute Gate

```python
if parsed.path == "/v1/query-workflows/execute":
    if not self.server.allow_execute:
        raise PermissionError("query workflow execute endpoint is disabled")
```

The execute endpoint is disabled by default and must be explicitly enabled with `--allow-execute`. This prevents accidental execution in development or demo environments. The healthz endpoint advertises `"allow_execute": false` so clients know before attempting the call.

### 4.3 `X-Request-Base-Dir` Header

```python
request_base_dir = self.headers.get("X-Request-Base-Dir", "").strip()
if request_base_dir:
    request_dir = Path(request_base_dir).expanduser()
    if not request_dir.is_absolute():
        raise ValueError("X-Request-Base-Dir must be an absolute path")
```

This header allows HTTP callers to specify the base directory for resolving relative paths in the request JSON — the same semantics as the CLI's `--request-file` directory. It enforces that the provided path must be absolute, preventing relative-path traversal via header injection.

### 4.4 Response Status on Execute

```python
status = HTTPStatus.OK if payload.get("manifest", {}).get("exit_code") in (None, 0) else HTTPStatus.BAD_GATEWAY
```

A non-zero pipeline exit code returns `502 Bad Gateway` rather than `200 OK` with an error body. This makes HTTP-level retry and error propagation correct for clients that inspect status codes rather than parsing the JSON body.

---

## 5. `serve_platform_health_api.py` — Platform Health Adapter

Re-exposes `scripts/check_platform_health.py` over HTTP without adding any new check logic. The health check itself is invoked as a subprocess, capturing its stdout as JSON:

```python
result = subprocess.run(
    [sys.executable, str(HEALTH_CHECK_PY), ...],
    capture_output=True, text=True, ...
)
payload = json.loads(result.stdout)
```

This means the HTTP adapter inherits all the same check coverage as the CLI, including completed-run artifact checks and metadata DB checks, without duplicating any health-check code.

---

## 6. Common Observations

### 6.1 Bearer Token Auth

All four adapters use plain string equality for auth:
```python
if provided != expected:
    raise PermissionError("... auth failed")
```

No HMAC, no constant-time comparison. For local loopback use (the intended deployment) this is acceptable — timing oracle attacks on token comparison require network-level access to exploit. If these adapters were exposed over a network, `hmac.compare_digest` should be used.

### 6.2 Lifecycle File Cleanup on Shutdown

All adapters remove `pid_file` and `ready_file` in the `finally` block after `serve_forever()` returns:

```python
finally:
    server.server_close()
    remove_file(args.ready_file)
    remove_file(args.pid_file)
```

This is the correct pattern: lifecycle files are removed when the server exits cleanly (via SIGTERM/SIGINT), making the absence of the ready file a reliable signal that the server has stopped.

### 6.3 No Request Logging

All four adapters suppress per-request logs (`log_message` returns immediately). For sidecar tools this reduces noise, but it also means there is no HTTP access log. If access auditing were required, `log_message` would need to write to a file rather than just suppressing.

### 6.4 No Rate Limiting

None of the four adapters implement rate limiting, connection limits, or request-body size limits. For local loopback use this is acceptable. Any external exposure would need these controls.

---

## 7. Identified Gaps / Observations

| Item | Severity | Adapter |
|---|---|---|
| Bearer token comparison is not constant-time | Low | All four |
| No per-request access log | Low | All four |
| No rate limiting or request-body size cap | Low | All four |
| Metadata API serializes all DB access with a global lock | Low | `serve_metadata_api.py` |
| Audit query API re-derives observability/lineage on every request | Low | `serve_audit_query_api.py` |
| Query workflow `X-Request-Base-Dir` not validated against an allowlist | Low | `serve_query_workflow_api.py` |
| Platform health runs a subprocess per request | Low | `serve_platform_health_api.py` |

---

## 8. Summary

The four sidecar HTTP adapters are consistently structured and correctly implement their single responsibility: exposing existing CLI tools and imported data over HTTP. The lifecycle file cleanup, startup validation, graceful shutdown, and execute gate are all well-designed. The main shared limitation is that bearer token comparison is not constant-time (low-risk for local loopback use). The query workflow adapter's `X-Request-Base-Dir` header enforcement (must be absolute) is a good defensive addition.
