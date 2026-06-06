#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Party A public bucketed mTLS wrapper. By default it keeps one shared public
# TLS_PORT across buckets, while incrementing the internal loopback PJC port per
# bucket to avoid reuse races on the host itself.

export RUN_PJC_SERVER_SH="${RUN_PJC_SERVER_SH:-$SCRIPT_DIR/run_pjc_server_tls.sh}"
export TLS_PORT_BASE="${TLS_PORT_BASE:-${TLS_PORT:-10502}}"
export PJC_LOCAL_PORT_BASE="${PJC_LOCAL_PORT_BASE:-${PJC_LOCAL_PORT:-10501}}"
export TLS_PORT_MODE="${TLS_PORT_MODE:-shared}"
export PJC_LOCAL_PORT_MODE="${PJC_LOCAL_PORT_MODE:-increment}"
export BIND_ADDR="${BIND_ADDR:-0.0.0.0}"

python3 - "$SCRIPT_DIR/run_pjc_bucketed_server.sh" <<'PY'
import os
import subprocess
import sys

script = sys.argv[1]
base_tls = int(os.environ.get("TLS_PORT_BASE", "10502"))
base_local = int(os.environ.get("PJC_LOCAL_PORT_BASE", "10501"))
job_dir = os.environ.get("JOB_DIR", "")
if not job_dir:
    raise SystemExit("JOB_DIR is required")

import json
from pathlib import Path

meta = json.loads((Path(job_dir) / "job_meta.json").read_text(encoding="utf-8"))
outputs = ((meta.get("bucket") or {}).get("outputs") or [])
tls_mode = os.environ.get("TLS_PORT_MODE", "shared").strip().lower() or "shared"
local_mode = os.environ.get("PJC_LOCAL_PORT_MODE", "increment").strip().lower() or "increment"
for idx, item in enumerate(outputs):
    env = os.environ.copy()
    env["JOB_DIR"] = job_dir
    env["TLS_PORT"] = str(base_tls if tls_mode == "shared" else base_tls + idx)
    env["PJC_LOCAL_PORT"] = str(base_local if local_mode == "shared" else base_local + idx)
    env["BUCKET_ONLY"] = str(item.get("bucket") or "")
    result = subprocess.run(["bash", script], env=env, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
PY
