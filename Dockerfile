# syntax=docker/dockerfile:1.7

# Stage 1: build the Rust bridge binary in a small Rust image.
# Bridge uses edition = "2024" + Cargo.lock v4, both requiring Rust >= 1.85.
FROM rust:1.85-bookworm AS bridge-builder

WORKDIR /src/bridge
COPY bridge/Cargo.toml bridge/Cargo.lock ./
COPY bridge/src ./src
COPY bridge/README.md ./README.md
COPY bridge/examples ./examples

RUN cargo build --release \
    && strip target/release/bridge \
    && cp target/release/bridge /usr/local/bin/bridge


# Stage 1b: build the operator console SPA (Vite + React).
FROM node:20-bookworm-slim AS console-builder

WORKDIR /src/console
# Copy package.json on its own first so a missing lockfile doesn't fail the COPY
# glob (BuildKit's behaviour with `package-lock.json*` is brittle when zero
# files match). The conditional below still uses `npm ci` if a lockfile gets
# committed later, but defaults to `npm install` for greenfield builds.
COPY console/package.json ./package.json
COPY console/ ./
RUN if [ -f package-lock.json ]; then \
      npm ci --no-audit --no-fund; \
    else \
      npm install --no-audit --no-fund; \
    fi \
    && npm run build


# Stage 2: install Python dependencies into a dedicated venv layer.
FROM python:3.11-slim-bookworm AS python-deps

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /opt/seccomp/build
COPY sse/requirements.txt /opt/seccomp/build/sse-requirements.txt

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/seccomp/venv \
    && /opt/seccomp/venv/bin/pip install --upgrade pip \
    && /opt/seccomp/venv/bin/pip install -r /opt/seccomp/build/sse-requirements.txt


# Stage 3: runtime image.
FROM python:3.11-slim-bookworm AS runtime

ARG GIT_REF=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="seccomp-privacy-platform" \
      org.opencontainers.image.description="End-to-end privacy computing platform (SSE + bridge + A-PSI / PJC + policy release)." \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/${REPO:-seccomp-privacy-platform}" \
      org.opencontainers.image.revision="${GIT_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/seccomp/venv/bin:/usr/local/bin:${PATH}" \
    SECCOMP_HOME=/opt/seccomp/platform

# Minimal runtime tooling: openssl for TLS material, ca-certificates for HTTPS,
# tini as a small PID 1, jq + curl for ops scripts.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates tini openssl jq curl bash \
    && rm -rf /var/lib/apt/lists/*

# Bring in the prebuilt Rust binary, the prebuilt venv, and the SPA bundle.
COPY --from=bridge-builder /usr/local/bin/bridge /usr/local/bin/bridge
COPY --from=python-deps /opt/seccomp/venv /opt/seccomp/venv
COPY --from=console-builder /src/console/dist /opt/seccomp/platform/console/dist

# Copy first-party source needed at runtime. Heavy third-party trees
# (a-psi/private-join-and-compute) stay out of the runtime image by default;
# attach them via volume if the PJC binaries are needed inside the container.
WORKDIR /opt/seccomp/platform
COPY sse/ ./sse/
COPY a-psi/moduleA_psi/ ./a-psi/moduleA_psi/
COPY scripts/ ./scripts/
COPY services/ ./services/
COPY migrations/ ./migrations/
COPY schemas/ ./schemas/
COPY config/ ./config/
COPY docs/ ./docs/
COPY README.md LICENSE NOTICE ./

# Add a non-root runtime user.
RUN groupadd --system seccomp \
    && useradd --system --gid seccomp --home-dir /opt/seccomp/platform --shell /bin/bash seccomp \
    && mkdir -p /var/lib/seccomp /var/log/seccomp \
    && chown -R seccomp:seccomp /opt/seccomp /var/lib/seccomp /var/log/seccomp

USER seccomp

# Default to the live SSE-backed demo as a smoke entrypoint. Override at run
# time, e.g.: `docker run ... seccomp-privacy bridge --help`.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "scripts/run_live_sse_bridge_demo.sh"]
