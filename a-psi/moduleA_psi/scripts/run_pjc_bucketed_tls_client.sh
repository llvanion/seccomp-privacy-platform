#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Party B public bucketed mTLS wrapper. Keeps TLS_PORT default 10502 and local
# client proxy default 10503, and reuses the existing TLS client helper.

export RUN_PJC_CLIENT_SH="${RUN_PJC_CLIENT_SH:-$SCRIPT_DIR/run_pjc_client_tls.sh}"
export TLS_PORT="${TLS_PORT:-10502}"
export LOCAL_PROXY_PORT="${LOCAL_PROXY_PORT:-10503}"

exec bash "$SCRIPT_DIR/run_pjc_bucketed_client.sh"
