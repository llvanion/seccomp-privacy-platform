# Code Review — Step 10: Security Tooling

**Scope:** `scripts/scan_repo_hygiene.py`, `scripts/check_dependency_hygiene.py`, `scripts/check_record_recovery_boundary.py`

---

## 1. `scan_repo_hygiene.py` — Repository Secret and Artifact Scanner

### 1.1 Design

The scanner operates on Git-tracked files only (`git ls-files -z`), falling back to `os.walk` when not in a git repo. This means it does not scan untracked files (intentional — those would generate too much noise from build artifacts and local state), but it also means a committed secret that is later `.gitignore`d will still be found.

Files are skipped if:
- They are in excluded directories: `.git`, `.venv`, `__pycache__`, `node_modules`, `target`, `tmp`
- They are probably binary (NUL byte detected in first 4096 bytes)
- They exceed the configurable `--max-file-bytes` threshold (default 1 MB)

### 1.2 Secret Detection Patterns

Two detection tiers:

**High-confidence patterns** (severity `error`):

| Kind | Pattern |
|---|---|
| `private_key_material` | `-----BEGIN * PRIVATE KEY-----` |
| `aws_access_key_id` | `(AKIA\|ASIA)[0-9A-Z]{16}` |
| `github_token` | `(ghp\|gho\|ghu\|ghs\|ghr)_[A-Za-z0-9_]{30,}` |
| `github_pat` | `github_pat_[A-Za-z0-9_]{40,}` |
| `slack_token` | `xox[baprs]-[A-Za-z0-9-]{20,}` |
| `openai_api_key` | `sk-(?:proj-)?[A-Za-z0-9_-]{40,}` |

**Generic secret assignment** (severity `warn`, skipped for `.md` files):
```python
GENERIC_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|private[_-]?key)\b\s*[:=]\s*['\"]([^'\"]{16,})['\"]"
)
```

Generic matches are filtered: values containing `"example"`, `"local-dev"`, or `"contract-"` are suppressed to avoid false positives on example configs. This is a targeted allowlist that avoids the common pattern of `token: "local-dev-secret"` in example JSON files.

### 1.3 Generated Artifact Detection

Separately from content scanning, the scanner checks for tracked generated artifacts (e.g. `.pyc`, `.so`, `.exe` files, files under `__pycache__/` or `target/`). These are reported as `warn` severity findings rather than errors — they indicate repository hygiene issues (generated files should generally not be tracked) but are not secrets.

### 1.4 Gap: No Entropy-Based Detection

The scanner uses only pattern matching, not entropy analysis. High-entropy strings that don't match known patterns (e.g. a randomly-generated 32-character bearer token without a recognizable prefix) will not be detected. This is a deliberate trade-off — entropy-based scanners generate many false positives on base64-encoded binary data, JSON examples, and test fixtures.

### 1.5 Gap: Max-findings Truncation

If `len(findings) >= max_findings` (default 200), the scan stops early. This means a repo with >200 findings may not report all of them. The `truncated` flag in the output indicates when this occurred.

---

## 2. `check_dependency_hygiene.py` — Dependency Reproducibility Check

### 2.1 Python Requirements

For each `requirements*.txt` file found in first-party directories (excluding `.git`, `.venv`, Bazel artifacts, and Rust `target/`), the checker scans logical requirement lines (handling line continuations with `\`) and asserts that every non-comment, non-include, non-index-url requirement is pinned with `==`, `~=`, or `===`:

```python
PY_REQ_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?\s*(==|~=|===)")
```

Requirements that only have lower/upper bound constraints (`>=`, `<`, `!=`) are flagged as unpinned.

### 2.2 Cargo.toml

For each `Cargo.toml` in first-party paths, the checker inspects `[dependencies]` for entries that use version ranges without an exact pin (`=` prefix). It emits `warn` for version ranges and `error` for path/git/workspace-path dependencies in first-party manifests.

### 2.3 What It Does Not Check

- It does not perform network requests (intentionally offline).
- It does not validate that pinned versions are not yanked or have CVEs.
- It does not check `uv.lock` or `Cargo.lock` directly for hash verification.

The purpose is a fast, offline first-pass reproducibility check — not a full supply-chain audit.

---

## 3. `check_record_recovery_boundary.py` — AST-Based Shim Enforcement

### 3.1 Design

This is an unusual use of Python's `ast` module: it statically checks that each `sse/toolkit/record_recovery_*.py` compatibility shim remains a *shim only* and does not re-acquire implementation logic.

For each shim file, it:
1. Parses the file with `ast.parse`.
2. Checks that the literal string `"Compatibility shim"` appears in the source text (shims must self-identify).
3. Checks that the file imports from the expected `services.record_recovery.*` module.
4. Walks the AST looking for `FunctionDef`, `AsyncFunctionDef`, or `ClassDef` nodes — **any of these trigger an error**.

```python
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        add_finding(..., kind="shim_contains_implementation", ...)
```

### 3.2 SHIMS Registry

```python
SHIMS = {
    "sse/toolkit/encrypted_record_store.py":      "services.record_recovery.encrypted_record_store",
    "sse/toolkit/record_recovery_authz.py":        "services.record_recovery.authz",
    "sse/toolkit/record_recovery_client.py":       "services.record_recovery.client",
    "sse/toolkit/record_recovery_common.py":       "services.record_recovery.common",
    "sse/toolkit/record_recovery_http_service.py": "services.record_recovery.http_service",
    "sse/toolkit/record_recovery_service.py":      "services.record_recovery.service",
    "sse/toolkit/record_recovery_service_config.py": "services.record_recovery.config",
    "sse/toolkit/record_recovery_worker.py":       "services.record_recovery.worker",
}
```

Each entry maps a legacy toolkit path to its authoritative implementation module. A shim is valid if and only if:
- It contains the self-identification marker.
- It imports from the corresponding `services.record_recovery.*` module.
- It defines no functions, async functions, or classes.

### 3.3 Effect

This check runs in CI via `check_ci_smoke.sh`. It prevents the following regression: a developer adds a utility function directly to a shim file (which is quick and expedient), causing the shim to gain implementation ownership and eventually becoming a fork of the service module rather than a transparent re-export.

The AST-based approach is more robust than a comment convention or a code-review checklist — it fails the build if implementation logic appears in a shim file.

### 3.4 Observed Limitation

The check requires that the shim self-identify via the literal string `"Compatibility shim"`. This is a low-friction but easily forgotten requirement for new shim files. However, since new shims must be added to the `SHIMS` registry to be checked at all, any new shim that doesn't self-identify will be caught when added to the registry.

---

## 4. Summary of Security Tooling Coverage

| Tool | What it catches | What it misses |
|---|---|---|
| `scan_repo_hygiene.py` | Known secret formats, tracked generated files | High-entropy anonymous tokens, secrets in untracked files |
| `check_dependency_hygiene.py` | Unpinned Python requirements, Cargo version ranges | CVEs, yanked packages, hash verification |
| `check_record_recovery_boundary.py` | Functions/classes added to shim files | Import-level aliasing that adds behavior via `__all__` manipulation |

Together, these three tools form a lightweight but genuinely useful security hygiene layer for a competition-scale prototype. They run in CI and block on error findings. The gap between this tooling and a production security posture (secret scanning with entropy, supply-chain hash verification, formal SBOM, SAST) is well-understood and documented as a residual risk.
