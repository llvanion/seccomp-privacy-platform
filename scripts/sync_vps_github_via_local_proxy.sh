#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  VPS_HOST=118.190.61.66 bash scripts/sync_vps_github_via_local_proxy.sh

Optional env:
  VPS_USER              SSH user on the VPS. Default: root
  VPS_REPO_DIR          Repo path on the VPS. Default: /root/seccomp-privacy-platform
  BRANCH                Branch to sync. Default: main
  LOCAL_PROXY_HOST      Local proxy host. Default: 127.0.0.1
  LOCAL_PROXY_PORT      Local proxy port. Default: auto from HTTPS_PROXY/HTTP_PROXY, else 10809
  VPS_PROXY_HOST        Remote bind host on VPS. Default: 127.0.0.1
  VPS_PROXY_PORT        Remote proxy port on VPS. Default: 7897
  SSH_CONTROL_PATH      SSH control socket. Default: /tmp/seccomp_vps_github_proxy_mux
  SSH_CONTROL_PERSIST   SSH control persist time. Default: 20m
  GIT_REMOTE            Git remote name. Default: origin
  KEEP_TUNNEL           1 keeps the tunnel after sync; 0 closes it. Default: 0

What it does:
  1. Opens an SSH reverse tunnel:
       VPS 127.0.0.1:7897 -> local 127.0.0.1:<LOCAL_PROXY_PORT>
  2. Verifies GitHub through the remote proxy from the VPS.
  3. Runs git fetch and git pull --ff-only on the VPS with temporary proxy env.

No password, token, or proxy secret is stored by this script.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

die() {
  echo "[error] $*" >&2
  exit 1
}

log() {
  echo "[info] $*"
}

infer_proxy_port() {
  python3 - <<'PY'
import os
from urllib.parse import urlparse

for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
    value = os.environ.get(name, "")
    if not value:
        continue
    parsed = urlparse(value)
    if parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port:
        print(parsed.port)
        raise SystemExit(0)
print("10809")
PY
}

VPS_HOST="${VPS_HOST:-}"
[[ -n "$VPS_HOST" ]] || die "set VPS_HOST=<ip-or-host>"

VPS_USER="${VPS_USER:-root}"
VPS_REPO_DIR="${VPS_REPO_DIR:-/root/seccomp-privacy-platform}"
BRANCH="${BRANCH:-main}"
LOCAL_PROXY_HOST="${LOCAL_PROXY_HOST:-127.0.0.1}"
LOCAL_PROXY_PORT="${LOCAL_PROXY_PORT:-$(infer_proxy_port)}"
VPS_PROXY_HOST="${VPS_PROXY_HOST:-127.0.0.1}"
VPS_PROXY_PORT="${VPS_PROXY_PORT:-7897}"
SSH_CONTROL_PATH="${SSH_CONTROL_PATH:-/tmp/seccomp_vps_github_proxy_mux}"
SSH_CONTROL_PERSIST="${SSH_CONTROL_PERSIST:-20m}"
GIT_REMOTE="${GIT_REMOTE:-origin}"
KEEP_TUNNEL="${KEEP_TUNNEL:-0}"

SSH_TARGET="${VPS_USER}@${VPS_HOST}"
REMOTE_PROXY_URL="http://${VPS_PROXY_HOST}:${VPS_PROXY_PORT}"

command -v ssh >/dev/null || die "ssh not found"
command -v nc >/dev/null || die "nc not found"

log "checking local proxy ${LOCAL_PROXY_HOST}:${LOCAL_PROXY_PORT}"
nc -z "$LOCAL_PROXY_HOST" "$LOCAL_PROXY_PORT" >/dev/null 2>&1 \
  || die "local proxy is not listening on ${LOCAL_PROXY_HOST}:${LOCAL_PROXY_PORT}"

cleanup() {
  if [[ "$KEEP_TUNNEL" != "1" ]]; then
    ssh -S "$SSH_CONTROL_PATH" -O exit "$SSH_TARGET" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if ssh -S "$SSH_CONTROL_PATH" -O check "$SSH_TARGET" >/dev/null 2>&1; then
  log "reusing existing SSH control connection: $SSH_CONTROL_PATH"
else
  rm -f "$SSH_CONTROL_PATH"
  log "opening reverse proxy tunnel: VPS ${VPS_PROXY_HOST}:${VPS_PROXY_PORT} -> local ${LOCAL_PROXY_HOST}:${LOCAL_PROXY_PORT}"
  ssh \
    -M -S "$SSH_CONTROL_PATH" \
    -fN \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ControlPersist="$SSH_CONTROL_PERSIST" \
    -R "${VPS_PROXY_HOST}:${VPS_PROXY_PORT}:${LOCAL_PROXY_HOST}:${LOCAL_PROXY_PORT}" \
    "$SSH_TARGET"
fi

log "verifying GitHub from VPS through ${REMOTE_PROXY_URL}"
ssh -S "$SSH_CONTROL_PATH" "$SSH_TARGET" \
  "HTTPS_PROXY='$REMOTE_PROXY_URL' HTTP_PROXY='$REMOTE_PROXY_URL' NO_PROXY='localhost,127.0.0.1' curl -fsSI --max-time 20 https://github.com >/tmp/seccomp_github_head.out && head -5 /tmp/seccomp_github_head.out"

log "syncing ${VPS_REPO_DIR} with ${GIT_REMOTE}/${BRANCH}"
ssh -S "$SSH_CONTROL_PATH" "$SSH_TARGET" \
  "set -e
   cd '$VPS_REPO_DIR'
   HTTPS_PROXY='$REMOTE_PROXY_URL' HTTP_PROXY='$REMOTE_PROXY_URL' NO_PROXY='localhost,127.0.0.1' git fetch '$GIT_REMOTE'
   HTTPS_PROXY='$REMOTE_PROXY_URL' HTTP_PROXY='$REMOTE_PROXY_URL' NO_PROXY='localhost,127.0.0.1' git pull --ff-only '$GIT_REMOTE' '$BRANCH'
   git status --short --branch
   printf 'HEAD='
   git rev-parse --short HEAD
   printf 'REMOTE='
   git rev-parse --short '$GIT_REMOTE/$BRANCH'"

if [[ "$KEEP_TUNNEL" == "1" ]]; then
  log "tunnel kept alive: $SSH_CONTROL_PATH"
else
  log "sync complete; tunnel will be closed"
fi
