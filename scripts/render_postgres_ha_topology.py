#!/usr/bin/env python3
import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_ID = "postgres_ha_topology_report/v1"
SERVICE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
WAL_KEEP_RE = re.compile(r"^[1-9][0-9]*(kB|MB|GB|TB)?$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require_service_name(value: str, *, field_name: str) -> str:
    candidate = str(value or "").strip()
    if not SERVICE_NAME_RE.match(candidate):
        raise ValueError(f"{field_name} must match {SERVICE_NAME_RE.pattern}")
    return candidate


def render_compose(
    *,
    project_name: str,
    postgres_image: str,
    db_name: str,
    app_user: str,
    replication_user: str,
    primary_service: str,
    replica_service: str,
    primary_port: int,
    replica_port: int,
    max_wal_senders: int,
    wal_keep_size: str,
) -> str:
    return f"""name: {project_name}
services:
  {primary_service}:
    image: {postgres_image}
    restart: unless-stopped
    environment:
      POSTGRES_DB: {db_name}
      POSTGRES_USER: {app_user}
      POSTGRES_PASSWORD: "${{POSTGRES_PRIMARY_PASSWORD:-CHANGE_ME_PRIMARY_PASSWORD}}"
      POSTGRES_REPLICATION_USER: {replication_user}
      POSTGRES_REPLICATION_PASSWORD: "${{POSTGRES_REPLICATION_PASSWORD:-CHANGE_ME_REPLICATION_PASSWORD}}"
      POSTGRES_INITDB_ARGS: "--auth-host=scram-sha-256"
    command:
      - postgres
      - -c
      - wal_level=replica
      - -c
      - max_wal_senders={max_wal_senders}
      - -c
      - wal_keep_size={wal_keep_size}
      - -c
      - hot_standby=on
    ports:
      - "{primary_port}:5432"
    volumes:
      - pg-primary-data:/var/lib/postgresql/data
      - ./primary-init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 5s
      timeout: 3s
      retries: 20

  {replica_service}:
    image: {postgres_image}
    restart: unless-stopped
    environment:
      PGDATA: /var/lib/postgresql/data
      POSTGRES_REPLICATION_USER: {replication_user}
      POSTGRES_REPLICATION_PASSWORD: "${{POSTGRES_REPLICATION_PASSWORD:-CHANGE_ME_REPLICATION_PASSWORD}}"
    command:
      - bash
      - -c
      - |
        set -euo pipefail
        if [ ! -s "$$PGDATA/PG_VERSION" ]; then
          rm -rf "$$PGDATA"/*
          until pg_isready -h {primary_service} -p 5432 -U "$$POSTGRES_REPLICATION_USER"; do
            sleep 1
          done
          PGPASSWORD="$$POSTGRES_REPLICATION_PASSWORD" pg_basebackup \\
            -h {primary_service} \\
            -D "$$PGDATA" \\
            -U "$$POSTGRES_REPLICATION_USER" \\
            -P \\
            -Xs \\
            -R
        fi
        exec postgres -c hot_standby=on
    depends_on:
      {primary_service}:
        condition: service_healthy
    ports:
      - "{replica_port}:5432"
    volumes:
      - pg-replica-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_REPLICATION_USER -d postgres"]
      interval: 5s
      timeout: 3s
      retries: 20

volumes:
  pg-primary-data:
  pg-replica-data:
"""


def render_primary_init() -> str:
    return r"""#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${POSTGRES_REPLICATION_USER:-}" || -z "${POSTGRES_REPLICATION_PASSWORD:-}" ]]; then
  echo "POSTGRES_REPLICATION_USER and POSTGRES_REPLICATION_PASSWORD are required" >&2
  exit 1
fi

if [[ ! "$POSTGRES_REPLICATION_USER" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "POSTGRES_REPLICATION_USER must be a simple PostgreSQL identifier" >&2
  exit 1
fi

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=replication_user="$POSTGRES_REPLICATION_USER" \
  --set=replication_password="$POSTGRES_REPLICATION_PASSWORD" <<'SQL'
SELECT format(
  'CREATE ROLE %I WITH REPLICATION LOGIN PASSWORD %L',
  :'replication_user',
  :'replication_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'replication_user')\gexec

SELECT format(
  'ALTER ROLE %I WITH REPLICATION LOGIN PASSWORD %L',
  :'replication_user',
  :'replication_password'
)
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'replication_user')\gexec
SQL

cat >> "$PGDATA/pg_hba.conf" <<HBA
host replication ${POSTGRES_REPLICATION_USER} 0.0.0.0/0 scram-sha-256
host replication ${POSTGRES_REPLICATION_USER} ::/0 scram-sha-256
HBA
"""


def render_verify_sql() -> str:
    return """SELECT
  client_addr,
  state,
  sent_lsn,
  write_lsn,
  flush_lsn,
  replay_lsn,
  pg_wal_lsn_diff(sent_lsn, replay_lsn) AS replay_lag_bytes
FROM pg_stat_replication;
"""


def render_env_example() -> str:
    return """POSTGRES_PRIMARY_PASSWORD=CHANGE_ME_PRIMARY_PASSWORD
POSTGRES_REPLICATION_PASSWORD=CHANGE_ME_REPLICATION_PASSWORD
"""


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def validate_text_artifacts(
    *,
    compose_text: str,
    init_text: str,
    verify_sql: str,
    primary_service: str,
    replica_service: str,
    primary_port: int,
    replica_port: int,
    max_wal_senders: int,
    wal_keep_size: str,
) -> list[dict[str, Any]]:
    checks = [
        ("primary_service_present", f"  {primary_service}:" in compose_text),
        ("replica_service_present", f"  {replica_service}:" in compose_text),
        ("postgres_16_image", "image: postgres:16" in compose_text),
        ("wal_level_replica", "wal_level=replica" in compose_text),
        ("max_wal_senders", f"max_wal_senders={max_wal_senders}" in compose_text),
        ("wal_keep_size", f"wal_keep_size={wal_keep_size}" in compose_text),
        ("primary_healthcheck", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB" in compose_text),
        ("replica_waits_for_primary", f"pg_isready -h {primary_service}" in compose_text),
        ("replica_basebackup", "pg_basebackup" in compose_text and "-R" in compose_text and "-Xs" in compose_text),
        ("replica_depends_on_primary_health", "condition: service_healthy" in compose_text),
        ("primary_port", f'"{primary_port}:5432"' in compose_text),
        ("replica_port", f'"{replica_port}:5432"' in compose_text),
        ("init_creates_replication_role", "WITH REPLICATION LOGIN" in init_text),
        ("init_updates_pg_hba", "pg_hba.conf" in init_text and "scram-sha-256" in init_text),
        ("verify_query_uses_pg_stat_replication", "pg_stat_replication" in verify_sql),
        ("verify_query_lsn_columns", all(col in verify_sql for col in ["sent_lsn", "write_lsn", "flush_lsn", "replay_lsn"])),
    ]
    return [
        {
            "name": name,
            "status": "ok" if ok else "fail",
            "detail": "present" if ok else "missing_or_mismatch",
        }
        for name, ok in checks
    ]


def run_docker_compose_config(compose_path: Path) -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        return {"status": "skipped", "reason": "docker_not_found"}
    proc = subprocess.run(
        [docker, "compose", "-f", str(compose_path), "config"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "status": "ok" if proc.returncode == 0 else "fail",
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Render a PostgreSQL primary/replica HA topology for the metadata sidecar.")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--output", default="", help="Optional report JSON output path")
    ap.add_argument("--project-name", default="seccomp-postgres-ha")
    ap.add_argument("--postgres-image", default="postgres:16")
    ap.add_argument("--db-name", default="seccomp_metadata")
    ap.add_argument("--app-user", default="seccomp")
    ap.add_argument("--replication-user", default="replicator")
    ap.add_argument("--primary-service", default="pg-primary")
    ap.add_argument("--replica-service", default="pg-replica")
    ap.add_argument("--primary-port", type=int, default=5432)
    ap.add_argument("--replica-port", type=int, default=5433)
    ap.add_argument("--max-wal-senders", type=int, default=3)
    ap.add_argument("--wal-keep-size", default="64MB")
    ap.add_argument("--docker-compose-config", action="store_true", help="Run 'docker compose config' when Docker is available")
    ap.add_argument("--assert-ok", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    try:
        primary_service = require_service_name(args.primary_service, field_name="primary_service")
        replica_service = require_service_name(args.replica_service, field_name="replica_service")
        if primary_service == replica_service:
            raise ValueError("primary_service and replica_service must differ")
        if args.primary_port <= 0 or args.replica_port <= 0:
            raise ValueError("ports must be positive")
        if args.primary_port == args.replica_port:
            raise ValueError("primary_port and replica_port must differ")
        if args.max_wal_senders < 1:
            raise ValueError("max_wal_senders must be positive")
        if not WAL_KEEP_RE.match(args.wal_keep_size):
            raise ValueError("wal_keep_size must be a positive PostgreSQL size, for example 64MB")
    except ValueError as exc:
        raise SystemExit(f"[ERROR] {exc}") from exc

    out_dir = Path(args.out_dir).resolve()
    compose_path = out_dir / "docker-compose.primary-replica.yml"
    init_path = out_dir / "primary-init" / "01-create-replicator.sh"
    verify_path = out_dir / "verify_replication.sql"
    env_path = out_dir / ".env.example"

    compose_text = render_compose(
        project_name=args.project_name,
        postgres_image=args.postgres_image,
        db_name=args.db_name,
        app_user=args.app_user,
        replication_user=args.replication_user,
        primary_service=primary_service,
        replica_service=replica_service,
        primary_port=args.primary_port,
        replica_port=args.replica_port,
        max_wal_senders=args.max_wal_senders,
        wal_keep_size=args.wal_keep_size,
    )
    init_text = render_primary_init()
    verify_sql = render_verify_sql()
    write_text(compose_path, compose_text)
    write_text(init_path, init_text)
    write_text(verify_path, verify_sql)
    write_text(env_path, render_env_example())

    checks = validate_text_artifacts(
        compose_text=compose_text,
        init_text=init_text,
        verify_sql=verify_sql,
        primary_service=primary_service,
        replica_service=replica_service,
        primary_port=args.primary_port,
        replica_port=args.replica_port,
        max_wal_senders=args.max_wal_senders,
        wal_keep_size=args.wal_keep_size,
    )
    docker_config = {"status": "not_requested"}
    if args.docker_compose_config:
        docker_config = run_docker_compose_config(compose_path)
        if docker_config.get("status") == "fail":
            checks.append(
                {
                    "name": "docker_compose_config",
                    "status": "fail",
                    "detail": docker_config.get("stderr") or docker_config.get("stdout") or "docker compose config failed",
                }
            )

    failed = [item for item in checks if item["status"] != "ok"]
    report = {
        "schema": SCHEMA_ID,
        "generated_at_utc": utc_now(),
        "status": "fail" if failed else "ok",
        "out_dir": str(out_dir),
        "compose_path": str(compose_path),
        "primary_service": primary_service,
        "replica_service": replica_service,
        "postgres_image": args.postgres_image,
        "primary_port": args.primary_port,
        "replica_port": args.replica_port,
        "replication_user": args.replication_user,
        "artifacts": [
            {"kind": "compose", "path": str(compose_path)},
            {"kind": "primary_init", "path": str(init_path)},
            {"kind": "verify_sql", "path": str(verify_path)},
            {"kind": "env_example", "path": str(env_path)},
        ],
        "checks": checks,
        "docker_compose_config": docker_config,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        write_text(Path(args.output), text + "\n")
    print(text)
    if args.assert_ok and report["status"] != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
