# Benchmark & Security Scan Plan — Seccomp Privacy Platform

## 1. Scope

This plan covers:
- Pipeline latency benchmarking (end-to-end and per-stage)
- Record recovery latency benchmarking
- PJC execution latency benchmarking
- Dependency vulnerability scanning
- Secret scanning (heuristic)
- Malformed input fuzz fixtures
- Schema backward-compatibility checks

All tools operate on existing files and CLI contracts.

## 2. Benchmark Suite

### 2.1 Pipeline End-to-End Latency

```bash
python3 scripts/benchmark_pipeline.py run \
  --iterations 5 \
  --out-base tmp/benchmark \
  --policy-config sse/config/export_policy.example.json
```

Measures full SSE → Bridge → PJC → Release wall-clock time per iteration.

### 2.2 Record Recovery Latency

Measured as part of the benchmark run:
- Encrypted record store creation time
- Recovery + export time (subprocess boundary)

### 2.3 Generate Benchmark Report

```bash
python3 scripts/benchmark_pipeline.py report \
  --benchmark-dir tmp/benchmark
```

Produces `BENCHMARK_REPORT.md` with:
- Min/max/mean/median/P95 latency
- Standard deviation
- Per-iteration breakdown

### 2.4 Benchmark Metrics

| Metric | Unit | Target |
|--------|------|--------|
| Pipeline e2e latency (file mode) | ms | < 30000 |
| SSE export latency | ms | < 10000 |
| Bridge tokenization latency | ms | < 5000 |
| PJC execution latency | ms | < 60000 |
| Policy release latency | ms | < 1000 |
| Record store creation (10 records) | ms | < 1000 |
| Record recovery (10 records) | ms | < 2000 |

### 2.5 Phase 2: Extended Benchmarks

- Larger dataset sizes (1K, 10K, 100K records)
- Concurrent pipeline runs (multi-tenant throughput)
- FIFO handoff vs file handoff comparison
- Subprocess vs socket recovery comparison
- Memory profiling per stage

## 3. Security Scanning

### 3.1 Full Scan

```bash
python3 scripts/security_scan.py scan --repo-root .
```

Runs:
1. **Secret scan**: Heuristic regex patterns for hardcoded secrets, API keys, private keys. Skips known safe patterns (demo secrets, example files, .venv).
2. **Dependency scan**: Enumerates dependency files (requirements.txt, Cargo.toml). Recommends `pip-audit` and `cargo audit` for CVE scanning.
3. **Schema compatibility check**: Validates all JSON schemas are syntactically valid and have consistent `$id` fields.

### 3.2 Malformed Input Fuzz Fixtures

```bash
python3 scripts/security_scan.py fuzz-fixtures --out-dir tmp/fuzz_fixtures
```

Generates malformed input fixtures for contract validation testing:

| Fixture | Type | Attack Vector |
|---------|------|---------------|
| Empty join key | CSV | Missing required field |
| Missing header | CSV | Parser confusion |
| Non-integer value | CSV | Type confusion |
| Empty file | CSV | Boundary condition |
| Non-JSON content | JSONL | Parser crash |
| Missing join key field | JSONL | Schema violation |
| Null join key | JSONL | Null dereference |
| Binary content | JSONL | Encoding attack |
| Short PJC hash | PJC CSV | Truncation attack |

Existing contract smoke (`scripts/check_json_contracts.sh`) already includes negative fixtures for bridge and PJC tabular inputs. These fuzz fixtures extend coverage.

### 3.3 Schema Backward-Compatibility Check

```bash
python3 scripts/security_scan.py schema-check --schema-dir schemas/
```

Checks:
- All schema files are valid JSON
- All schemas have `$id` fields
- All object schemas have `properties`
- Schema versions follow naming conventions

## 4. Integration with CI

Proposed GitHub Actions workflow additions:

```yaml
# .github/workflows/security-scan.yml
- name: Security scan
  run: python3 scripts/security_scan.py scan

- name: Fuzz fixtures
  run: |
    python3 scripts/security_scan.py fuzz-fixtures --out-dir tmp/fuzz_fixtures
    for f in tmp/fuzz_fixtures/bad_*.csv; do
      python3 scripts/validate_tabular_contract.py \
        --contract bridge-input-csv --path "$f" --role client \
        --join-key-field email --value-field amount \
        && echo "ERROR: should have failed: $f" && exit 1 \
        || echo "OK: correctly rejected $f"
    done

- name: Schema compatibility
  run: python3 scripts/security_scan.py schema-check
```

## 5. Phase 2: Production-Grade Scanning

- Integrate `pip-audit` / `cargo audit` for CVE scanning
- Integrate `trufflehog` or `gitleaks` for deeper secret scanning
- Add fuzz testing with `python-afl` or `cargo-fuzz` for parsers
- Add unsafe deserialization review (pickle, yaml.load)
- Add untrusted input boundary review for all CLI entrypoints
- Add SBOM generation (CycloneDX / SPDX)

## 6. Verification

```bash
# Generate fuzz fixtures and verify they are all rejected
python3 scripts/security_scan.py fuzz-fixtures --out-base tmp/fuzz_test
for f in tmp/fuzz_test/bad_*.csv; do
  if python3 scripts/validate_tabular_contract.py \
    --contract bridge-input-csv --path "$f" --role client \
    --join-key-field email --value-field amount 2>/dev/null; then
    echo "FAIL: $f was not rejected"
  else
    echo "PASS: $f correctly rejected"
  fi
done

# Run security scan
python3 scripts/security_scan.py scan
```
