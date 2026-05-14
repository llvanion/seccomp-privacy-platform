# Code Review — Step 4: Record Recovery Service

**Scope:** `services/record_recovery/` — all owned implementation files.

---

## 1. Module Purpose

The record recovery service is the long-lived boundary between encrypted record stores and the bridge pipeline. Its responsibilities:

1. Accept recovery requests from the SSE export client.
2. Validate the request: auth token, HMAC signature, timestamp anti-replay, caller authz.
3. Decrypt and return only the candidate rows matching the provided IDs, within configured output root restrictions.
4. Emit structured `sse_record_recovery_service_audit/v1` audit records.

Two transport adapters exist: Unix socket (`service.py`) and HTTP (`http_service.py`). Both share the same request handling, authz, and audit logic through the common modules.

The service is separately deployable from the SSE CLI — the preferred launcher is `scripts/run_record_recovery_service.py`. The `sse/toolkit/record_recovery_*.py` files are compatibility shims that re-export from here.

---

## 2. Security Layer: `common.py`

### 2.1 Request Timestamp Validation

```python
REQUEST_TIMESTAMP_MAX_SKEW_SEC = 30

def validate_request_timestamp(ts_str, *, max_skew_sec=30):
    # Missing timestamp → accepted (backward compat)
    # Present but wrong → rejected
```

The 30-second window is tighter than typical API implementations (often 5 minutes). This limits replay attack windows. Requests without a timestamp are accepted by the timestamp helper for backward compatibility, but authenticated `recover` requests now require the timestamp as signature metadata. The client (`client.py`) always injects `request_timestamp_utc` for new requests.

**Observation:** The backward-compatibility path (missing timestamp → accepted) means the timestamp anti-replay check is opt-in. Any client that omits the timestamp is not protected. In practice, the provided client always sends the timestamp, but this could be a gap if a third-party client is used.

### 2.2 Request Signing

```python
def _canonical_request_message(request_id, request_timestamp_utc, op):
    return f"{request_id}:{request_timestamp_utc}:{op}:{request_payload_sha256}"

def sign_request(auth_token, *, request_id, request_timestamp_utc, op, request_payload_sha256):
    msg = _canonical_request_message(...)
    return hmac.new(auth_token.encode(), msg.encode(), sha256).hexdigest()

def verify_request_signature(auth_token, *, request_id, ..., provided_sig):
    expected = sign_request(...)
    return hmac.compare_digest(expected, provided_sig)  # constant-time
```

The canonical message binds four fields:
- `request_id` (UUID4): prevents reuse of a valid signature for a different request.
- `request_timestamp_utc`: prevents replays of old signed requests.
- `op`: prevents cross-operation misuse (e.g. using a `recover` signature for a different op).
- `request_payload_sha256`: prevents post-signature mutation of request contents such as candidate IDs, paths, and bounds.

The comparison uses `hmac.compare_digest` (constant-time), correctly avoiding timing oracle attacks.

---

## 3. Authorization: `authz.py` — Full Analysis

### 3.1 Policy Source Dispatch (`load_authz_policy`)

Three policy sources are supported, selected by the `schema` field of the pointed-to JSON file:

| Source schema | What happens |
|---|---|
| `sse_export_policy/v1` | Delegates to `load_platform_policy` + `platform_policy_for_caller` |
| `record_recovery_authz_source/v1` | Queries `caller_permissions` from the metadata SQLite DB and synthesizes an `sse_export_policy/v1` view |
| `record_recovery_service_policy/v1` | Legacy narrower service-only policy (passed through as-is) |

Empty path → returns `{}` (no authz, all requests permitted). This is the correct behavior when no authz config is configured — the service falls back to the `allowed_callers` list as the only gate.

### 3.2 SQL-Backed Authz Source

The `record_recovery_authz_source/v1` path queries:
```sql
SELECT cp.caller, cp.permission_key, cp.permission_value, ...
FROM caller_permissions cp JOIN policies p ON p.policy_id = cp.policy_id
WHERE p.schema_name = ?  [AND cp.policy_id = ? AND p.path = ?]
ORDER BY cp.imported_at_utc DESC, cp.id DESC
```

Results are deduplicated by `(caller, permission_key)` in first-seen order (most recently imported wins). This reconstructs the equivalent of the flat `callers: { caller_id: { permission_key: permission_value } }` dict from the `sse_export_policy/v1` schema.

**Edge case:** If the DB exists but returns zero rows for the given policy filter, an error is raised rather than silently allowing all callers. This is a safe default.

### 3.3 `authorize_record_recovery_request` — Per-Request Authz

The main authz function is called once per `recover` request. It checks, in order:

1. **Policy schema dispatch:** If the policy is `sse_export_policy/v1`, extract the caller-specific sub-policy via `platform_policy_for_caller` and `resolve_platform_scope`, then normalize it to the narrower dict form.

2. **Caller lookup and enabled check:** Caller must exist in `policy["callers"]` and `enabled` must not be `False` (note: missing `enabled` key defaults to `True` — same semantics as the export policy).

3. **Field-level access control** (all via `_as_set` returning empty set = no restriction):
   - `allowed_roles`: role (server/client) must be in the set if non-empty.
   - `allowed_join_key_fields`: join key field must be in the set if non-empty.
   - `allowed_value_fields`: value field must be in the set if non-empty.
   - `required_filters`: all required filter fields must be present in the request.
   - `allowed_filter_fields`: no filter may use a field not in the set if non-empty.

4. **Per-value filter allowlist** (`_ensure_allowed_filter_values`): For each `(field, value)` in the request's filters, if `allowed_filter_values[field]` is configured, the value must be in that list. This allows fine-grained restriction to specific campaign IDs, tenant scopes, etc.

5. **Candidate count cap** (`max_candidate_count`): If the policy sets a max, the request's `candidate_count` must not exceed it.

6. **Row count negotiation** (the return value):
   - Policy `min_output_rows` / `max_output_rows` are combined with the request's values using `max(request, policy)` and `min(request, policy)` respectively.
   - If the request's explicit limits conflict with policy (e.g. `requested_min_output_rows < policy_min`), the request is rejected.
   - Otherwise the effective limits are returned to the caller for `enforce_row_limits`.

7. **Path prefix checks** (`_ensure_prefix`):
   - `allowed_output_prefixes`: output path must be under one of these resolved prefixes.
   - `allowed_record_store_prefixes`: record store path must be under one of these resolved prefixes.
   - Both use `Path.resolve()` for canonicalization.

**Observation:** The authz function returns the negotiated row limits rather than enforcing them directly. This is a clean separation — `authz.py` decides the allowed limits, `common.py:enforce_row_limits` enforces them after row selection. It also means the same limit negotiation logic is reused for both the service path and the worker subprocess path.

### 3.4 `authz_policy_path` Accessor

A small helper that reads the `_config_file` private field embedded by `load_authz_policy`. This is used by the service state to record the authz config path in health responses and audit records without re-parsing the policy.

---

## 4. Row Selection and Output: `common.py` — Full Analysis

### 4.1 `HashingTextWriter`

The output writer wraps a file handle and transparently computes a SHA-256 digest of every byte written:

```python
class HashingTextWriter:
    def write(self, data: str):
        self._hash.update(data.encode("utf-8"))
        return self._sink.write(data)
    def hexdigest(self) -> str:
        return self._hash.hexdigest()
```

`write_selected_rows` threads the `csv.DictWriter` or JSONL writer through this wrapper, so the output SHA-256 is computed in a single pass over the data without re-reading the file. The digest is returned to the caller and recorded in the result payload and service audit.

### 4.2 `parse_candidate_payload`

```python
def parse_candidate_payload(payload):
    candidate_ids = payload["candidate_ids"]   # must be a list
    filters = payload.get("filters", [])       # list of [field, value] pairs
    return {stringify_record_id(item) for item in candidate_ids}, parsed_filters
```

`stringify_record_id` normalizes candidate IDs:
- `bytes` → UTF-8 decode, fallback to hex.
- Anything else → `str(value)`.

This allows candidate IDs to arrive as strings, integers, or bytes without breaking the set membership check in `iter_candidate_rows`.

Filters are parsed as `[[field, value], ...]` pairs. Any non-two-element list is rejected with an explicit error, preventing silent filter bypass via malformed input.

### 4.3 `selected_bridge_row` — Row Projection

```python
def selected_bridge_row(*, row, role, join_key_field, value_field, filters):
    if not row_matches_filters(row, filters):    return None
    join_value = row.get(join_key_field)
    if join_value in (None, ""):                 return None
    selected = {join_key_field: join_value}
    if role == "client":
        metric = row.get(value_field)
        if metric in (None, ""):                 return None
        selected[value_field] = metric
    return selected
```

For server role: only the join key is projected. For client role: join key plus value. Any row with a missing/empty join key or (for client) missing/empty value is silently dropped. This mirrors the bridge's behavior of dropping rows with blank join keys.

**Observation:** Silently dropping rows with empty values could mask data quality issues. In production a warning log for dropped rows would be useful.

### 4.4 `enforce_row_limits`

```python
def enforce_row_limits(*, output_rows, min_rows, max_rows):
    if max_rows is not None and output_rows > max_rows:
        raise ValueError(...)
    if min_rows is not None and output_rows < min_rows:
        raise ValueError(...)
```

Both bounds are checked. The min-rows check is important for privacy: it prevents a caller from configuring `min_output_rows=0` and then inferring membership from zero-row responses. The bound negotiation in `authz.py` ensures the effective `min_rows` is at least the policy minimum even if the caller doesn't request one.

---

## 5. Service Transport: `service.py` (Unix socket)

The Unix socket adapter uses Python's `socketserver.ThreadingMixIn` with `socketserver.UnixStreamServer`:

```python
class RecordRecoveryUnixStreamServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
```

Per-connection handling:
1. Read full request JSON from socket.
2. If `op == "health"`: return health response.
3. If `op == "recover"`:
   a. Check auth token (if configured).
   b. Validate request timestamp.
   c. Verify HMAC request signature (if provided).
   d. Authorize caller via authz policy.
   e. Check output path is within `allowed_output_roots`.
   f. Check record store path is within `allowed_record_store_roots`.
   g. Decrypt and write rows to output path.
   h. Enforce row limits (`max_rows_per_request`).
   i. Write service audit record.

Path restrictions (`_path_within_roots`) use `Path.resolve()` to prevent path traversal attacks.

---

## 6. HTTP Transport: `http_service.py`

The HTTP adapter exposes:
- `GET /healthz` — unauthenticated health check (returns 200 OK).
- `GET /health` — authenticated health check (returns `sse_record_recovery_health/v1`).
- `POST /recover` — authenticated recovery operation.

Authentication via `Authorization: Bearer <token>` header or `auth_token` in JSON body. Request signature metadata via `X-Request-Signature`, `X-Request-Payload-SHA256`, and `X-Request-Signature-Algorithm` headers.

Proxy bypass: The client (`client.py`) implements `_should_bypass_proxy` to detect loopback and private IP addresses and disable HTTP proxy for those, preventing proxy misconfiguration from routing internal recovery traffic to an external proxy.

---

## 7. Recovery Client: `client.py`

The client is the single point of contact for both Unix-socket and HTTP transports. It:

1. Generates a UUID4 `request_id` per request.
2. Injects `request_timestamp_utc` (current UTC ISO8601).
3. Computes `request_payload_sha256` over the canonical payload, then attaches `request_signature` (HMAC-SHA256 of canonical message).
4. For HTTP: sets `X-Request-Signature`, `X-Request-Payload-SHA256`, and `X-Request-Timestamp` headers.
5. Routes to `_send_unix_request` or `_send_http_request` based on which transport config is provided.

The `_http_operation_url` helper correctly maps `op` to paths (`/health`, `/recover`) on the base `endpoint_url`, preventing accidental posting to the root URL.

---

## 8. systemd Hardening: `manage_record_recovery_service.py` / `render-systemd`

The `render-systemd` command generates a systemd unit with full Linux security directives:

```ini
ProtectSystem=strict
ProtectHome=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
LockPersonality=true
RestrictSUIDSGID=true
SystemCallFilter=@system-service
ReadWritePaths=<auto-derived from runtime config>
```

`ReadWritePaths` is auto-derived from:
- `audit_log` directory
- `socket_path` directory (Unix socket)
- `pid_file` and `ready_file` directories
- `allowed_output_roots` and `allowed_record_store_roots`

This limits the service's write footprint to exactly the directories needed for its function. Contract smoke verifies all hardening directives are present in the generated unit.

---

## 8. `manage_record_recovery_service.py` — Lifecycle Manager

### 8.1 `cmd_start`

Starts the recovery service as a detached subprocess:

```python
proc = subprocess.Popen(
    build_service_command(runtime),
    cwd=str(SSE_DIR),
    stdout=log_handle,
    stderr=log_handle,
    start_new_session=True,   # detaches from parent process group
)
```

`start_new_session=True` is the critical detail — it moves the subprocess into a new process group so it is not killed when the parent shell's process group receives SIGINT. This is the correct approach for a supervised background service.

After starting, the manager waits for the socket or HTTP endpoint to become ready:
```python
if transport == "http":
    wait_for_http_url(endpoint_url, ...)
else:
    wait_for_socket(socket_path, timeout_sec=args.timeout_sec)
```

A PID file is required for `start` — this is enforced at startup, not just at stop time, because the PID file is how the manager detects whether the service is already running.

### 8.2 `cmd_stop`

Reads PID from the PID file, verifies it is running, sends SIGTERM, then polls for exit:

```python
os.kill(pid, signal.SIGTERM)
wait_for_exit(pid, timeout_sec=args.timeout_sec)
```

Does not fall back to SIGKILL. If the service does not exit within `timeout_sec`, the stop command fails. This is conservative — production supervisors would typically escalate to SIGKILL after a grace period, but for a local lifecycle manager this is fine.

### 8.3 `derive_writable_paths` — Minimal Write Footprint

```python
def derive_writable_paths(runtime):
    dirs = []
    _add(runtime.get("audit_log", ""))        # audit log directory
    _add(runtime.get("socket_path", ""))       # socket parent directory
    _add(runtime.get("pid_file", ""))          # pid file parent directory
    _add(runtime.get("ready_file", ""))        # ready file parent directory
    for root in runtime.get("allowed_output_roots", []):
        _add(str(root) + "/")                  # each output root
```

The helper uses `str(p.parent if p.suffix or p.name else p)` to extract the parent directory of a file path or the directory itself for paths without extensions. The result feeds directly into `ReadWritePaths=` in the systemd unit.

**Observation:** `allowed_record_store_roots` are intentionally **not** included in `ReadWritePaths`. The record store is read-only from the service's perspective; it only needs write access to the output roots and lifecycle files. This is the minimal-privilege approach.

### 8.4 systemd Unit Security Directives

The generated unit includes the full set of Linux hardening directives (documented in §7). Additional details:
- `UMask=0077` — all new files created by the service are mode 600 by default.
- `NoNewPrivileges=true` — the service cannot gain elevated privileges via setuid/setcap.
- For HTTP transport: `After=network-online.target` and `Wants=network-online.target` are added, so the unit waits for network before starting.

The `EnvironmentFile=` directive receives a generated env-template listing the env vars that should be populated (e.g. `auth_token_env`). The template has placeholder values, reminding operators to fill them in before enabling the unit.

---

## 9. Identified Gaps / Observations

| Item | Severity | Note |
|---|---|---|
| Missing timestamp → accepted (backward compat) | Medium | The anti-replay check is opt-in; only the provided client enforces it |
| Payload-bound request signing | Closed | HMAC now includes `request_payload_sha256`; the service rejects hash/signature mismatch |
| Unix socket `ThreadingMixIn` can saturate thread pool | Low | No connection limit or thread pool ceiling configured |
| `_path_within_roots` allows symlinks in `allowed_output_roots` | Low | `Path.resolve()` follows symlinks; an operator could misconfigure the root |
| Rate limiting per-service not per-tenant | Informational | `max_rows_per_request` caps per-request rows, not per-caller |
| Recovery is a linear scan of the encrypted store | Low | Acceptable for prototype scale; needs indexing for large stores |
| SQL-backed authz DB path is resolved relative to source file | Informational | Path resolution logic uses `base_dir` of the authz source config — correct, but can be confusing |

---

## 9. Worker Subprocess: `worker.py`

The worker subprocess is the third recovery mode (in addition to Unix socket and HTTP service). It runs in a separate Python process launched by the export command:

```
export command (parent)
  → subprocess.Popen("python3 services/record_recovery/worker.py ...")
  → writes JSON payload to worker stdin: {candidate_ids, filters}
  → worker decrypts store, selects rows, writes output file
  → worker prints result JSON to stdout: {input_rows, output_rows, output_sha256}
  → parent reads stdout only (no sensitive data crosses the boundary)
```

IPC design:
- Candidate IDs and filters go **in** via `sys.stdin` as a JSON payload (parsed by `parse_candidate_payload`).
- The worker writes the bridge-ready file directly to `--out-path`.
- The worker returns only non-sensitive metadata (row counts and SHA-256 of the output) via stdout.
- No raw record values or decrypted plaintext ever cross back to the parent process.

The subprocess boundary means that even if the parent process is compromised after the call, it cannot retroactively read the decrypted store contents — only the already-written output file is accessible.

---

## 10. `_path_within_roots` — Path Traversal Prevention

```python
def _path_within_roots(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False
```

`Path.resolve()` canonicalizes symlinks before the containment check. This prevents a symlink in the output directory from pointing outside the allowed root. One edge case: if `allowed_output_roots` contains a symlink that points to a sensitive directory, the attacker could add a legitimate-looking path that resolves to a sensitive location — but this requires root-level write access to the filesystem to set up.

---

## 11. Updated Gaps / Observations

_(The original gap table at §8 still applies. Added items from deeper review:)_

| Item | Severity | Note |
|---|---|---|
| Worker subprocess stdin payload is not size-limited | Low | A very large candidate ID set could cause the worker to OOM; `max_rows_per_request` caps output but not input |
| Worker stdout is fully read before the parent continues | Informational | Correct; avoids deadlock since the parent does not hold any pipe open for writing when reading stdout |
| `allowed_output_roots` symlink edge case | Low | `resolve()` prevents traversal through symlinks in the *path*, but not through a root that is itself a symlink pointing elsewhere |

---

## 12. Service Internals: `runtime.py`, `config.py`, `observability.py`, `launcher.py`

### 12.1 `runtime.py` — Service State and Construction

`RecordRecoveryServiceState` is a `@dataclass` that collects all service-level configuration and runtime state:

```python
@dataclass
class RecordRecoveryServiceState:
    service_id: str
    tenant_id: str
    dataset_id: str
    auth_token: str
    allowed_callers: set[str]
    authz_policy: dict
    authz_policy_path_value: str | None
    allowed_output_roots: list[Path]
    allowed_record_store_roots: list[Path]
    audit_log: Path | None
    transport: str = "unix_socket"
    socket_path: str | None = None
    endpoint_url: str | None = None
    max_rows_per_request: int = 0  # 0 = unlimited
```

`max_rows_per_request = 0` means "unlimited" — a non-zero value enforces a hard cap on rows returned per recovery request. Both the Unix-socket and HTTP adapters enforce this cap via `enforce_row_limits` in `common.py`.

`build_service_state` assembles the state from raw CLI/config arguments, calling `read_optional_env` for the auth token and `load_authz_policy` for the authz policy (loading the policy at startup, not per-request).

**Observation:** Loading the authz policy at startup means a policy file change requires a service restart. This is consistent with the current static-file-backed authz design.

### 12.2 `config.py` — Runtime Config Resolution

`resolve_record_recovery_service_config` resolves the flat `record_recovery_service_config/v1` JSON into a normalized runtime dict. Key behaviors:

- **Transport auto-detection:** If `transport` is absent, it defaults to `"http"` when `endpoint_url` or `http_listener` is present, otherwise `"unix_socket"`.
- **Endpoint URL auto-construction:** If `endpoint_url` is absent but `http_listener.bind_host` and `http_listener.port` are present, the endpoint URL is constructed as `http://<bind_host>:<port>`.
- **Relative path resolution:** All path fields (`socket_path`, `authz_config`, `audit_log`, etc.) are resolved relative to the config file's directory using `resolve_relative_path`. This allows config files to use relative paths portably.

`merged_record_recovery_service_scope_value` enforces that if both an explicit CLI value and a config value are present for `service_id`, `tenant_id`, or `dataset_id`, they must be identical:

```python
if raw and config and raw != config:
    raise ValueError(f"conflicting {field_name}: explicit {raw!r} does not match config {config!r}")
```

This prevents silent scope confusion when CLI arguments partially override a config file.

### 12.3 `observability.py` — Structured Service Log Emission

`emit_structured_service_log` writes `record_recovery_service_log/v1` JSONL records to **stdout** (not to the audit log). This is a deliberate design choice: stdout logs are captured by the service supervisor (systemd journald, or the orchestrator's subprocess stdout redirect), while the audit log captures per-request decisions.

Each structured log record includes:
- `pid`: current process ID (useful for distinguishing restart cycles in logs).
- `service_id`, `tenant_id`, `dataset_id`: non-sensitive scope fields.
- `transport`, `server_address`: transport type and socket/endpoint.
- Additional keyword fields passed by the caller.

`new_request_id()` returns `uuid4().hex` — a 32-character lowercase hex string. This is used as the per-request correlation ID in both the service log and the audit record.

### 12.4 `launcher.py` — Unified `serve` Dispatch

The standalone launcher (`scripts/run_record_recovery_service.py`) dispatches through `launcher.py:_serve`, which:

1. Resolves the combined CLI + config runtime via `_resolved_runtime`.
2. Converts the resolved runtime into a synthetic `sys.argv` list.
3. Calls `_dispatch(http_service_main or unix_service_main, argv)` — which temporarily replaces `sys.argv` with the synthetic list, calls the target `main()`, and restores `sys.argv` on exit.

The `sys.argv` injection pattern allows the service `main()` functions (which use `argparse`) to be reused without modification — the launcher just constructs the right argument list programmatically. This avoids duplicating argument parsing logic across three entrypoints (SSE CLI, standalone launcher, and direct service invocation).

### 12.5 HTTP Service: Header Promotion

The HTTP adapter (`http_service.py`) promotes request headers into the payload dict before forwarding to the common handler:

```python
header_ts = self.headers.get("X-Request-Timestamp", "").strip()
if header_ts and not payload.get("request_timestamp_utc"):
    payload["request_timestamp_utc"] = header_ts
header_sig = self.headers.get("X-Request-Signature", "").strip()
if header_sig and not payload.get("request_signature"):
    payload["request_signature"] = header_sig
header_payload_hash = self.headers.get("X-Request-Payload-SHA256", "").strip()
if header_payload_hash and not payload.get("request_payload_sha256"):
    payload["request_payload_sha256"] = header_payload_hash
```

This means the timestamp, payload hash, and signature can be sent either in headers (preferred for HTTP) or in the JSON body (legacy/JSON-only clients). The payload field takes precedence if both are present. The common handler then validates them identically regardless of which channel they arrived through.

---

## 13. Summary

The record recovery service correctly implements the most security-critical boundary in the platform: it separates the encrypted record store from the bridge pipeline, enforces caller authz, validates request timestamps, and verifies request signatures with constant-time comparison. The worker subprocess IPC design is notably clean — sensitive row data never crosses back to the parent. The service state dataclass centralizes all runtime configuration, the config resolver enforces scope field consistency, the launcher reuses service `main()` functions via `sys.argv` injection, and the observability module separates service logs (stdout) from per-request audit records (audit log). The systemd hardening is comprehensive. The main remaining gaps are the opt-in nature of the timestamp check (backward compat) and the fact that the signature does not bind the full payload.
