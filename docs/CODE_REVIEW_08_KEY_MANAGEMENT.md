# Code Review — Step 8: Key Management

**Scope:** `scripts/keyring_lib.py`, `scripts/key_agent_service.py`, `scripts/request_key_agent.py`, `scripts/manage_keyring.py`, `scripts/external_kms_service.py`, `scripts/request_external_kms.py`, `scripts/manage_external_kms.py`, `config/keyring.example.json`, `config/external_kms.example.json`

---

## 1. Overview

The platform has two key-management boundaries for the bridge token secret:

| Boundary | Files | Transport | Lifecycle |
|---|---|---|---|
| Local keyring + key agent | `keyring_lib.py`, `key_agent_service.py` | Unix socket | Rotate/deactivate via `manage_keyring.py` |
| External HTTP KMS (mock) | `external_kms_service.py`, `request_external_kms.py` | HTTP | Rotate/set-status via `manage_external_kms.py` |

Both boundaries share the same `keyring_lib.py` for lifecycle logic, and both emit `key_access_audit/v1` and `key_lifecycle_audit/v1` records in a consistent format.

---

## 2. `keyring_lib.py` — Shared Lifecycle Logic

### 2.1 Keyring Structure

```json
{
  "schema": "keyring/v1",
  "keys": {
    "bridge-token": {
      "purpose": "bridge_token",
      "active_version": "demo-v1",
      "allowed_callers": ["auto_demo"],
      "versions": {
        "demo-v1": {
          "enabled": true,
          "status": "active",
          "created_at_utc": "...",
          "secret_ref": { "kind": "env", "name": "BRIDGE_TOKEN_SECRET" }
        }
      }
    }
  }
}
```

Key design decisions:
- Secrets are never stored in the keyring file itself — only `secret_ref` (currently only `kind=env`) pointing to an env var name.
- `active_version` points to the current key version; only one version is active at a time.
- `allowed_callers` gates which pipeline callers may access the key.

### 2.2 `ensure_key_access_allowed`

This is the central access-control gate for both the key agent and external KMS:

```python
def ensure_key_access_allowed(*, keyring, key_name, purpose, caller):
    # 1. Key must exist
    # 2. Purpose must match key's declared purpose (no cross-purpose reuse)
    # 3. Active version must have status="active" and enabled=True
    # 4. Caller must be in allowed_callers (if list is non-empty)
    # 5. secret_ref.kind must be "env" (only supported kind)
    # 6. Env var must be set in the process environment
    return version, key_value, version_value, env_name
```

**Observation:** `allowed_callers = []` (empty list) is treated as "no restriction" — the key is accessible to any caller. This is counterintuitive; an empty list is normally the safe default (deny all). In practice the example keyring always sets allowed_callers explicitly, but this should be documented.

### 2.3 Key Rotation (`rotate_key`)

The rotation function:
1. Adds a new version entry with the caller-supplied `secret_env` name.
2. If `activate=True`, calls `promote_version` which marks the new version `active` and all others `inactive`.
3. Raises if the version name already exists (prevents accidental overwrite).
4. Supports `create_key=True` to create a key entry that does not yet exist.

**Observation:** `promote_version` uses a loop over all versions to find and mark other active versions as `inactive`. This is correct for the current key count (1–3 versions), but O(N) over all versions.

### 2.4 Audit Records

Both `key_access_audit/v1` and `key_lifecycle_audit/v1` include:
- `manifest_sha256` / `keyring_sha256`: SHA-256 of the config file at audit time.
- `secret_source`: always `{"kind": "env", "name": "<env_var>"}` — the env var name is logged, never the secret value.
- `resolver`: kind, socket_path, or endpoint_url depending on which resolver was used.

This correctly separates "what env var to look in" from "what the secret is".

---

## 3. `key_agent_service.py` — Local Unix Socket Key Agent

Architecture: same pattern as the record recovery service — `socketserver.ThreadingMixIn` + `UnixStreamServer`.

Request/response contract:
```json
// Request
{"key_name": "bridge-token", "purpose": "bridge_token", "caller": "auto_demo", "auth_token": "...", "job_id": "..."}

// Response (success)
{"schema": "key_agent_result/v1", "key_id": "bridge-token", "key_version": "demo-v1", "secret": "<env_var_value>"}

// Response (error)
{"schema": "key_agent_error/v1", "error": "..."}
```

Authentication: `auth_token` field in the request body compared with server-side expected token. This is a simple shared-secret check — not HMAC-signed (unlike the recovery service). For a local Unix socket agent this is lower risk since the socket is filesystem-protected.

**Observation:** The key agent response includes `"secret": "<actual_secret_value>"` in plaintext JSON. This is the correct behavior (the caller needs the secret to inject into the bridge environment variable), but it means the secret travels over the Unix socket in cleartext. The socket is mode 600 by default, limiting OS-level access, but this is a deliberate design choice documented as "local dev boundary, not production KMS".

After each request, the agent writes a `key_access_audit/v1` record regardless of success or failure. On failure, the deny record is written with `reason_code="request_failed"` before the error response is sent.

---

## 4. `external_kms_service.py` — Mock External HTTP KMS

The external KMS service exposes three API endpoints:

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /healthz` | None | Liveness check |
| `POST /v1/resolve` | Bearer token (read) | Resolve active key secret |
| `POST /v1/admin/rotate` | Bearer token (admin) | Add new key version |
| `POST /v1/admin/set-status` | Bearer token (admin) | Change version status |

Separate auth tokens for read (`auth_token`) and admin (`admin_auth_token`) operations correctly follow the principle of least privilege.

The `state_lock` (`threading.Lock`) is acquired for every read or write of the state file. This prevents concurrent rotate/resolve races, but means all operations serialize on this lock. For a mock service this is fine; a real KMS would use atomic transactions.

**Important:** Like the key agent, `POST /v1/resolve` returns `"secret": "<value>"` in the JSON response. The calling code (`request_external_kms.py`) immediately injects this into a bridge-only env var and never logs the value. The `key_access_audit/v1` record logs the `env_name` from `secret_ref`, not the resolved value.

---

## 5. `request_key_agent.py` — Key Agent Client

A minimal Unix-socket client used by the pipeline orchestrator to resolve a secret from the running key agent:

```python
payload = {"caller": ..., "job_id": ..., "key_name": ..., "purpose": ...}
if args.auth_token_env:
    payload["auth_token"] = os.environ[args.auth_token_env]
# connect, send, receive, print JSON result to stdout
```

The auth token is injected from the environment variable named by `--auth-token-env`, not from the CLI argument value itself. The pipeline reads the `secret` field from the returned JSON and injects it into a bridge-only environment variable — it never logs it.

Schema validation is strict:
```python
if result.get("schema") == "key_agent_error/v1":
    raise SystemExit(f"[ERROR] {result.get('error', ...)}")
if result.get("schema") != "key_agent_result/v1":
    raise SystemExit(f"[ERROR] unexpected key agent schema: ...")
```

The output (which contains the secret) goes to stdout. The pipeline captures this via subprocess `stdout=PIPE` and extracts only the `secret` field — the full JSON with the secret is never written to any log file.

---

## 6. `request_external_kms.py` + `external_kms_lib.py` — External KMS Client

### 6.1 `external_kms_lib.py` — HTTP Client Layer

The external KMS client library uses a unified `_json_request` function for all operations:

```python
def _json_request(config, *, method, path, payload=None, admin=False):
    token = auth_token(config, admin=admin)  # different env vars for read vs admin
    headers["Authorization"] = f"Bearer {token}"
    ...
```

**Proxy bypass** (same pattern as the recovery service client):
```python
def _should_bypass_proxy(url):
    # returns True for: localhost, *.localhost, loopback IPs, private IPs, link-local IPs
```

This prevents loopback KMS requests from being routed through corporate HTTP proxies.

**Error schema unwrapping:** If the HTTP response contains `{"schema": "external_kms_error/v1", "error": "..."}`, the error message is extracted and re-raised as a Python `RuntimeError`, giving the caller a clean error message rather than a raw HTTP 4xx/5xx.

The library provides three distinct operations:
- `resolve_secret_via_external_kms` → `POST /v1/resolve` (read token)
- `rotate_external_key` → `POST /v1/admin/rotate` (admin token)
- `set_external_key_status` → `POST /v1/admin/set-status` (admin token)

### 6.2 `request_external_kms.py` — Audit-First Error Handling

Unlike `request_key_agent.py`, the external KMS client always writes a `key_access_audit/v1` record — both on success and on failure:

```python
try:
    result = resolve_secret_via_external_kms(...)
    append_key_access_audit(..., decision="allow", reason_code="ok", ...)
except Exception as e:
    append_key_access_audit(..., decision="deny", reason_code="request_failed",
                            reason=str(e), ...)
    raise SystemExit(f"[ERROR] {e}") from e
```

This is a stronger audit guarantee than the key agent path, where the audit is written by the server rather than the client. Since the external KMS is an HTTP boundary, network failures, auth failures, and KMS-side errors all appear as deny records in the client-side audit.

The `secret_source.kind` in the audit record is `"external_kms"` and `secret_source.name` is the endpoint URL — which is logged without any token or secret value.

---

## 7. `manage_keyring.py` — Lifecycle CLI

Subcommands:
- `describe`: prints key names, active versions, status, and allowed callers. Does not print secrets.
- `rotate`: adds a new version, optionally activates it, writes `key_lifecycle_audit/v1`.
- `set-status`: changes a version to `active`, `inactive`, or `retired`. Setting `active` automatically calls `promote_version`.

The CLI requires `--caller` for all mutating operations, so lifecycle changes are auditable by caller.

---

## 8. Secret Flow Through the Pipeline

For the `--token-secret-key-name + --keyring` path:

```
run_sse_bridge_pipeline.sh
  → auto-starts key_agent_service.py (socket at tmp/<hash>.sock)
  → calls request_key_agent.py → gets {"secret": "<value>"}
  → exports BRIDGE_TOKEN_SECRET=<value> into bridge's env only
  → calls bridge with --token-secret-env BRIDGE_TOKEN_SECRET
  → bridge reads from env, never CLI
  → writes key_access_audit.jsonl (env name only, not value)
  → stops key_agent_service.py
```

For the `--token-secret-key-name + --external-kms-config` path, the same flow applies with `external_kms_service.py` replacing the key agent.

The secret value touches:
1. The process environment of the bridge subprocess only.
2. The key agent/KMS service's memory (never written to disk).
3. The Unix socket or HTTP response payload (cleartext, but scoped).

It never appears in:
- Any log file.
- Any audit record.
- The audit chain.
- Any CLI argument (production mode enforces this).

---

## 9. Identified Gaps / Observations

| Item | Severity | Note |
|---|---|---|
| `allowed_callers = []` means "no restriction" | Medium | Empty list should arguably mean "deny all"; needs documentation |
| Key agent auth is plain equality check, not HMAC | Low | Acceptable for Unix socket; HMAC would be overkill for local process |
| External KMS returns secret in HTTP response body | Medium | Correct behavior for a mock; real production KMS should use asymmetric encryption for secret transport |
| `state_lock` serializes all KMS operations | Low | Acceptable for mock; production needs atomic transactions |
| `secret_ref.kind` is hardcoded to `"env"` only | Informational | Expected for current scope; real KMS would support HSM/vault/cloud-KMS kinds |
| Keyring file is mutable on disk | Informational | `rotate_key` + `save_json_object` writes the keyring atomically via `json.dump` but not via temp-file+rename |
| No TTL on key agent connections | Low | A slow client can hold a connection indefinitely |

---

## 10. Summary

The key management layer is well-designed for a prototype. It correctly separates secrets from config (secrets only in env vars, config in files), produces comprehensive audit records, enforces purpose and caller restrictions, and integrates cleanly with the pipeline. The mock external KMS correctly separates read and admin auth tokens. The main production gap is that `secret_ref.kind=env` is the only supported backend — a real deployment needs Vault, cloud KMS, or HSM integration.
