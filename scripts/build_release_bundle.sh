#!/usr/bin/env bash
# Build all release artifacts locally and stage them under dist/release/.
#
# Outputs (each with a matching .sha256 file):
#   dist/release/bridge-<host-triple>.tar.gz       Rust bridge binary
#   dist/release/seccomp-privacy-cli-<host>.tar.gz PyInstaller-bundled CLIs
#   dist/release/seccomp-privacy-platform-<tag>-source.tar.gz
#                                                  git archive source bundle
#   dist/release/seccomp-privacy-platform-<tag>.docker.tar.gz
#                                                  optional, only when --docker
#
# Skips steps gracefully when the required toolchain is missing:
#   cargo missing      -> skip bridge build
#   python missing     -> skip PyInstaller bundle
#   pyinstaller missing-> skip PyInstaller bundle
#   docker missing     -> skip docker image (only built with --docker)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

TAG="${RELEASE_TAG:-$(git describe --tags --always --dirty 2>/dev/null || echo v0.0.0-dev)}"
HOST_TRIPLE="${HOST_TRIPLE:-$(rustc -vV 2>/dev/null | awk -F': ' '/^host/ {print $2}' || echo unknown-host)}"
HOST_TAG="${HOST_TAG:-${HOST_TRIPLE}}"

DIST_DIR="${ROOT_DIR}/dist/release"
STAGING_DIR="${ROOT_DIR}/dist/release-staging"

BUILD_DOCKER="false"
SKIP_PYINSTALLER="false"
SKIP_BRIDGE="false"
SKIP_SOURCE="false"
SKIP_CONSOLE="false"

usage() {
  cat <<USAGE
Usage: $0 [--docker] [--skip-bridge] [--skip-pyinstaller] [--skip-source] [--skip-console]

Environment overrides:
  RELEASE_TAG=<tag>       Override the tag string (default: git describe)
  HOST_TRIPLE=<triple>    Override the Rust host target triple
  HOST_TAG=<label>        Override the host label used in archive names
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker) BUILD_DOCKER="true" ;;
    --skip-bridge) SKIP_BRIDGE="true" ;;
    --skip-pyinstaller) SKIP_PYINSTALLER="true" ;;
    --skip-source) SKIP_SOURCE="true" ;;
    --skip-console) SKIP_CONSOLE="true" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

mkdir -p "${DIST_DIR}" "${STAGING_DIR}"
rm -rf "${STAGING_DIR}"/*

log() { printf "[build-release] %s\n" "$*" >&2; }

write_sha256() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$(dirname "${file}")" && sha256sum "$(basename "${file}")" > "$(basename "${file}").sha256")
  elif command -v shasum >/dev/null 2>&1; then
    (cd "$(dirname "${file}")" && shasum -a 256 "$(basename "${file}")" > "$(basename "${file}").sha256")
  else
    log "skip sha256 for ${file}: no sha256sum/shasum available"
  fi
}

build_bridge() {
  if [[ "${SKIP_BRIDGE}" == "true" ]]; then
    log "skipping bridge build (--skip-bridge)"
    return 0
  fi
  if ! command -v cargo >/dev/null 2>&1; then
    log "cargo not found; skipping bridge build"
    return 0
  fi

  log "building bridge release binary"
  (cd "${ROOT_DIR}/bridge" && cargo build --release)

  local bin="${ROOT_DIR}/bridge/target/release/bridge"
  if [[ ! -f "${bin}" ]]; then
    log "expected ${bin} after build; aborting bridge package"
    return 1
  fi

  local stage="${STAGING_DIR}/bridge-${HOST_TAG}"
  mkdir -p "${stage}"
  cp "${bin}" "${stage}/"
  cp -f LICENSE NOTICE bridge/README.md "${stage}/" 2>/dev/null || true

  local archive="${DIST_DIR}/bridge-${HOST_TAG}.tar.gz"
  tar -czf "${archive}" -C "${STAGING_DIR}" "bridge-${HOST_TAG}"
  write_sha256 "${archive}"
  log "wrote ${archive}"
}

build_pyinstaller() {
  if [[ "${SKIP_PYINSTALLER}" == "true" ]]; then
    log "skipping PyInstaller bundle (--skip-pyinstaller)"
    return 0
  fi
  local python="${PYTHON:-python3}"
  if ! command -v "${python}" >/dev/null 2>&1; then
    log "${python} not found; skipping PyInstaller bundle"
    return 0
  fi
  if ! "${python}" -m PyInstaller --version >/dev/null 2>&1; then
    log "PyInstaller not installed for ${python}; skipping. Install with:"
    log "  ${python} -m pip install pyinstaller"
    return 0
  fi

  log "running PyInstaller for run_client / run_record_recovery_service / init_metadata_db"
  (cd "${ROOT_DIR}" && "${python}" -m PyInstaller --clean --noconfirm packaging/pyinstaller/run_client.spec)
  (cd "${ROOT_DIR}" && "${python}" -m PyInstaller --clean --noconfirm packaging/pyinstaller/run_record_recovery_service.spec)
  (cd "${ROOT_DIR}" && "${python}" -m PyInstaller --clean --noconfirm packaging/pyinstaller/init_metadata_db.spec)

  local stage="${STAGING_DIR}/seccomp-privacy-cli-${HOST_TAG}"
  mkdir -p "${stage}"
  cp -r "${ROOT_DIR}/dist/seccomp-sse-client" "${stage}/" 2>/dev/null || true
  cp -r "${ROOT_DIR}/dist/seccomp-record-recovery-service" "${stage}/" 2>/dev/null || true
  cp -r "${ROOT_DIR}/dist/seccomp-init-metadata-db" "${stage}/" 2>/dev/null || true
  cp -f LICENSE NOTICE "${stage}/" 2>/dev/null || true

  local archive="${DIST_DIR}/seccomp-privacy-cli-${HOST_TAG}.tar.gz"
  tar -czf "${archive}" -C "${STAGING_DIR}" "seccomp-privacy-cli-${HOST_TAG}"
  write_sha256 "${archive}"
  log "wrote ${archive}"
}

build_console() {
  if [[ "${SKIP_CONSOLE}" == "true" ]]; then
    log "skipping console build (--skip-console)"
    return 0
  fi
  if ! command -v npm >/dev/null 2>&1; then
    log "npm not found; skipping console build"
    return 0
  fi
  if [[ ! -d "${ROOT_DIR}/console" ]]; then
    log "console/ directory missing; skipping"
    return 0
  fi

  log "building operator console SPA"
  local install_log="${DIST_DIR}/console-install.log"
  local build_log="${DIST_DIR}/console-build.log"
  local ok="true"

  if [[ -f "${ROOT_DIR}/console/package-lock.json" ]]; then
    (cd "${ROOT_DIR}/console" && npm ci --no-audit --no-fund) > "${install_log}" 2>&1 || ok="false"
  else
    (cd "${ROOT_DIR}/console" && npm install --no-audit --no-fund) > "${install_log}" 2>&1 || ok="false"
  fi

  if [[ "${ok}" != "true" ]]; then
    log "npm install failed; skipping console build. See ${install_log}"
    return 0
  fi

  if ! (cd "${ROOT_DIR}/console" && npm run build) > "${build_log}" 2>&1; then
    log "npm run build failed; skipping console package. See ${build_log}"
    return 0
  fi

  if [[ ! -d "${ROOT_DIR}/console/dist" ]]; then
    log "console/dist missing after build; skipping package"
    return 0
  fi

  local stage="${STAGING_DIR}/console-static-${TAG}"
  mkdir -p "${stage}"
  cp -r "${ROOT_DIR}/console/dist/." "${stage}/"
  cp -f LICENSE NOTICE "${stage}/" 2>/dev/null || true

  local archive="${DIST_DIR}/console-static-${TAG}.tar.gz"
  tar -czf "${archive}" -C "${STAGING_DIR}" "console-static-${TAG}"
  write_sha256 "${archive}"
  log "wrote ${archive}"
}

build_source_tarball() {
  if [[ "${SKIP_SOURCE}" == "true" ]]; then
    log "skipping source tarball (--skip-source)"
    return 0
  fi
  if ! command -v git >/dev/null 2>&1; then
    log "git not found; skipping source tarball"
    return 0
  fi
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "not inside a git work tree; skipping source tarball"
    return 0
  fi

  local archive="${DIST_DIR}/seccomp-privacy-platform-${TAG}-source.tar.gz"
  git archive --format=tar.gz --prefix="seccomp-privacy-platform-${TAG}/" -o "${archive}" HEAD
  write_sha256 "${archive}"
  log "wrote ${archive}"
}

build_docker_image() {
  if [[ "${BUILD_DOCKER}" != "true" ]]; then
    return 0
  fi
  if ! command -v docker >/dev/null 2>&1; then
    log "docker not found; skipping docker image"
    return 0
  fi

  local tag="seccomp-privacy-platform:${TAG}"
  log "building docker image ${tag}"
  docker build -t "${tag}" -f Dockerfile .

  local archive="${DIST_DIR}/seccomp-privacy-platform-${TAG}.docker.tar.gz"
  docker save "${tag}" | gzip > "${archive}"
  write_sha256 "${archive}"
  log "wrote ${archive}"
}

write_manifest() {
  local manifest="${DIST_DIR}/release-manifest.json"
  local files_json=()
  for f in "${DIST_DIR}"/*.tar.gz "${DIST_DIR}"/*.zip; do
    [[ -e "${f}" ]] || continue
    local name; name="$(basename "${f}")"
    local size; size="$(stat -c%s "${f}" 2>/dev/null || stat -f%z "${f}" 2>/dev/null || echo 0)"
    files_json+=("{\"name\":\"${name}\",\"size_bytes\":${size}}")
  done
  local now; now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local joined=""
  if [[ ${#files_json[@]} -gt 0 ]]; then
    joined="$(IFS=,; echo "${files_json[*]}")"
  fi
  printf '{"tag":"%s","host":"%s","built_at":"%s","files":[%s]}\n' \
    "${TAG}" "${HOST_TAG}" "${now}" "${joined}" > "${manifest}"
  log "wrote ${manifest}"
}

build_bridge
build_pyinstaller
build_console
build_source_tarball
build_docker_image
write_manifest

log "done. artifacts in ${DIST_DIR}:"
ls -la "${DIST_DIR}" >&2
