#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BRIDGE_DIR="$REPO_ROOT/bridge"

if ! command -v cargo >/dev/null 2>&1; then
  echo "[ERROR] cargo is required for bridge Rust checks" >&2
  exit 1
fi

cd "$BRIDGE_DIR"

cargo fmt --check

tmp_target="$(mktemp -d /tmp/bridge_cargo_test.XXXXXX)"
cleanup() {
  rm -rf "$tmp_target"
}
trap cleanup EXIT

CARGO_TARGET_DIR="$tmp_target" cargo test

echo "[ok] bridge Rust checks passed"
