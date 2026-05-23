#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Party A public bucketed mTLS wrapper. Keeps TLS_PORT default 10502 and runs
# each business bucket sequentially through the existing TLS server helper.

export RUN_PJC_SERVER_SH="${RUN_PJC_SERVER_SH:-$SCRIPT_DIR/run_pjc_server_tls.sh}"
export TLS_PORT="${TLS_PORT:-10502}"
export PJC_LOCAL_PORT="${PJC_LOCAL_PORT:-10501}"
export BIND_ADDR="${BIND_ADDR:-0.0.0.0}"

exec bash "$SCRIPT_DIR/run_pjc_bucketed_server.sh"
