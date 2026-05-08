#!/usr/bin/env python3
import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_ID = "pgbouncer_topology_report/v1"
SERVICE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
POSTGRES_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
POOL_MODES = {"transaction", "session", "statement"}
AUTH_TYPES = {"md5", "scram-sha-256"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require_service_name(value: str, *, field_name: str) -> str:
    candidate = str(value or "").strip()
    if not SERVICE_NAME_RE.match(candidate):
        raise ValueError(f"{field_name} must match {SERVICE_NAME_RE.pattern}")
    return candidate


def require_identifier(value: str, *, field_name: str) -> str:
    candidate = str(value or "").strip()
    if not POSTGRES_IDENTIFIER_RE.match(candidate):
        raise ValueError(f"{field_name} must match {POSTGRES_IDENTIFIER_RE.pattern}")
    return candidate


def render_pgbouncer_ini(
    *,
    database_name: str,
    primary_host: str,
    primary_port: int,
    upstream_dbname: str,
    listen_port: int,
    pool_mode: str,
    max_client_conn: int,
    default_pool_size: int,
    auth_type: str,
) -> str:
    return f"""[databases]
{database_name} = host={primary_host} port={primary_port} dbname={upstream_dbname}

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = {listen_port}
pool_mode = {pool_mode}
max_client_conn = {max_client_conn}
default_pool_size = {default_pool_size}
auth_type = {auth_type}
auth_file = /etc/pgbouncer/userlist.txt
ignore_startup_parameters = extra_float_digits
server_reset_query = DISCARD ALL
admin_users = pgbouncer_admin
stats_users = pgbouncer_admin
"""


def render_userlist(*, app_user: str, admin_user: str) -> str:
    return f""""{app_user}" "md5CHANGE_ME_REPLACE_WITH_POSTGRES_MD5_HASH"
"{admin_user}" "md5CHANGE_ME_REPLACE_WITH_ADMIN_MD5_HASH"
"""


def render_compose(
    *,
    project_name: str,
    pgbouncer_image: str,
    pgbouncer_service: str,
    primary_service: str,
    listen_port: int,
) -> str:
    return f"""name: {project_name}
services:
  {pgbouncer_service}:
    image: {pgbouncer_image}
    restart: unless-stopped
    ports:
      - "{listen_port}:{listen_port}"
    volumes:
      - ./pgbouncer.ini:/etc/pgbouncer/pgbouncer.ini:ro
      - ./userlist.txt.example:/etc/pgbouncer/userlist.txt:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -p {listen_port} -U pgbouncer_admin -d pgbouncer"]
      interval: 5s
      timeout: 3s
      retries: 20
    depends_on:
      - {primary_service}
"""


def render_commands(
    *,
    app_user: str,
    admin_user: str,
    pgbouncer_host: str,
    pgbouncer_port: int,
    database_name: str,
    primary_host: str,
    primary_port: int,
) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

APP_DSN="${{APP_DSN:-postgresql://{app_user}:CHANGE_ME@{pgbouncer_host}:{pgbouncer_port}/{database_name}}}"
ADMIN_DSN="${{ADMIN_DSN:-postgresql://{admin_user}:CHANGE_ME@{pgbouncer_host}:{pgbouncer_port}/pgbouncer}}"
DIRECT_PRIMARY_DSN="${{DIRECT_PRIMARY_DSN:-postgresql://{app_user}:CHANGE_ME@{primary_host}:{primary_port}/{database_name}}}"

psql "$APP_DSN" -c "SELECT 1;"
psql "$ADMIN_DSN" -c "SHOW POOLS;"
psql "$ADMIN_DSN" -c "SHOW STATS;"

# Long write transactions such as apply-registry should use this direct
# primary DSN or a separate pgBouncer session-mode listener.
python3 scripts/manage_metadata_db.py --db-dsn "$DIRECT_PRIMARY_DSN" status
python3 scripts/benchmark_read_adapters.py --db-dsn "$APP_DSN" --iterations 1
"""


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def validate_text_artifacts(
    *,
    ini_text: str,
    userlist_text: str,
    compose_text: str,
    commands_text: str,
    database_name: str,
    primary_host: str,
    primary_port: int,
    pgbouncer_service: str,
    pgbouncer_port: int,
    pool_mode: str,
    max_client_conn: int,
    default_pool_size: int,
    app_user: str,
    admin_user: str,
) -> list[dict[str, Any]]:
    checks = [
        ("database_mapping", f"{database_name} = host={primary_host} port={primary_port}" in ini_text),
        ("listen_port", f"listen_port = {pgbouncer_port}" in ini_text),
        ("transaction_pool_mode", f"pool_mode = {pool_mode}" in ini_text),
        ("client_pool_limits", f"max_client_conn = {max_client_conn}" in ini_text and f"default_pool_size = {default_pool_size}" in ini_text),
        ("auth_file", "auth_file = /etc/pgbouncer/userlist.txt" in ini_text),
        ("startup_parameter_compat", "ignore_startup_parameters = extra_float_digits" in ini_text),
        ("admin_stats_users", "admin_users = pgbouncer_admin" in ini_text and "stats_users = pgbouncer_admin" in ini_text),
        ("userlist_app_user", f'"{app_user}"' in userlist_text),
        ("userlist_admin_user", f'"{admin_user}"' in userlist_text),
        ("compose_service", f"  {pgbouncer_service}:" in compose_text),
        ("compose_image", "pgbouncer" in compose_text),
        ("compose_port", f'"{pgbouncer_port}:{pgbouncer_port}"' in compose_text),
        ("compose_mounts_config", "pgbouncer.ini:/etc/pgbouncer/pgbouncer.ini:ro" in compose_text and "userlist.txt.example:/etc/pgbouncer/userlist.txt:ro" in compose_text),
        ("compose_healthcheck", "pg_isready" in compose_text and "-d pgbouncer" in compose_text),
        ("commands_show_pools", "SHOW POOLS;" in commands_text),
        ("commands_show_stats", "SHOW STATS;" in commands_text),
        ("commands_direct_primary_for_writes", "DIRECT_PRIMARY_DSN" in commands_text and "manage_metadata_db.py --db-dsn" in commands_text),
        ("commands_read_benchmark_uses_pool", "benchmark_read_adapters.py --db-dsn \"$APP_DSN\"" in commands_text),
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
    ap = argparse.ArgumentParser(description="Render pgBouncer topology artifacts for metadata PostgreSQL pooling.")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--output", default="", help="Optional report JSON output path")
    ap.add_argument("--project-name", default="seccomp-pgbouncer")
    ap.add_argument("--pgbouncer-image", default="edoburu/pgbouncer:1.24.0-p0")
    ap.add_argument("--pgbouncer-service", default="pgbouncer")
    ap.add_argument("--pgbouncer-host", default="pgbouncer")
    ap.add_argument("--pgbouncer-port", type=int, default=6432)
    ap.add_argument("--primary-service", default="pg-primary")
    ap.add_argument("--primary-host", default="pg-primary")
    ap.add_argument("--primary-port", type=int, default=5432)
    ap.add_argument("--database-name", default="seccomp_metadata")
    ap.add_argument("--upstream-dbname", default="postgres")
    ap.add_argument("--app-user", default="seccomp")
    ap.add_argument("--admin-user", default="pgbouncer_admin")
    ap.add_argument("--pool-mode", default="transaction", choices=sorted(POOL_MODES))
    ap.add_argument("--max-client-conn", type=int, default=200)
    ap.add_argument("--default-pool-size", type=int, default=20)
    ap.add_argument("--auth-type", default="md5", choices=sorted(AUTH_TYPES))
    ap.add_argument("--docker-compose-config", action="store_true", help="Run 'docker compose config' when Docker is available")
    ap.add_argument("--assert-ok", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    try:
        pgbouncer_service = require_service_name(args.pgbouncer_service, field_name="pgbouncer_service")
        primary_service = require_service_name(args.primary_service, field_name="primary_service")
        require_service_name(args.pgbouncer_host, field_name="pgbouncer_host")
        require_service_name(args.primary_host, field_name="primary_host")
        database_name = require_identifier(args.database_name, field_name="database_name")
        upstream_dbname = require_identifier(args.upstream_dbname, field_name="upstream_dbname")
        app_user = require_identifier(args.app_user, field_name="app_user")
        admin_user = require_identifier(args.admin_user, field_name="admin_user")
        if pgbouncer_service == primary_service:
            raise ValueError("pgbouncer_service and primary_service must differ")
        if args.pgbouncer_port <= 0 or args.primary_port <= 0:
            raise ValueError("ports must be positive")
        if args.max_client_conn < 1 or args.default_pool_size < 1:
            raise ValueError("pool sizes must be positive")
        if args.max_client_conn < args.default_pool_size:
            raise ValueError("max_client_conn must be greater than or equal to default_pool_size")
    except ValueError as exc:
        raise SystemExit(f"[ERROR] {exc}") from exc

    out_dir = Path(args.out_dir).resolve()
    ini_path = out_dir / "pgbouncer.ini"
    userlist_path = out_dir / "userlist.txt.example"
    compose_path = out_dir / "docker-compose.pgbouncer.yml"
    commands_path = out_dir / "pgbouncer_commands.sh"

    ini_text = render_pgbouncer_ini(
        database_name=database_name,
        primary_host=args.primary_host,
        primary_port=args.primary_port,
        upstream_dbname=upstream_dbname,
        listen_port=args.pgbouncer_port,
        pool_mode=args.pool_mode,
        max_client_conn=args.max_client_conn,
        default_pool_size=args.default_pool_size,
        auth_type=args.auth_type,
    )
    userlist_text = render_userlist(app_user=app_user, admin_user=admin_user)
    compose_text = render_compose(
        project_name=args.project_name,
        pgbouncer_image=args.pgbouncer_image,
        pgbouncer_service=pgbouncer_service,
        primary_service=primary_service,
        listen_port=args.pgbouncer_port,
    )
    commands_text = render_commands(
        app_user=app_user,
        admin_user=admin_user,
        pgbouncer_host=args.pgbouncer_host,
        pgbouncer_port=args.pgbouncer_port,
        database_name=database_name,
        primary_host=args.primary_host,
        primary_port=args.primary_port,
    )

    write_text(ini_path, ini_text)
    write_text(userlist_path, userlist_text)
    write_text(compose_path, compose_text)
    write_text(commands_path, commands_text)

    checks = validate_text_artifacts(
        ini_text=ini_text,
        userlist_text=userlist_text,
        compose_text=compose_text,
        commands_text=commands_text,
        database_name=database_name,
        primary_host=args.primary_host,
        primary_port=args.primary_port,
        pgbouncer_service=pgbouncer_service,
        pgbouncer_port=args.pgbouncer_port,
        pool_mode=args.pool_mode,
        max_client_conn=args.max_client_conn,
        default_pool_size=args.default_pool_size,
        app_user=app_user,
        admin_user=admin_user,
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
        "pgbouncer_service": pgbouncer_service,
        "pgbouncer_host": args.pgbouncer_host,
        "pgbouncer_port": args.pgbouncer_port,
        "primary_service": primary_service,
        "primary_host": args.primary_host,
        "primary_port": args.primary_port,
        "database_name": database_name,
        "upstream_dbname": upstream_dbname,
        "pool_mode": args.pool_mode,
        "max_client_conn": args.max_client_conn,
        "default_pool_size": args.default_pool_size,
        "auth_type": args.auth_type,
        "app_dsn": f"postgresql://{app_user}:CHANGE_ME@{args.pgbouncer_host}:{args.pgbouncer_port}/{database_name}",
        "direct_primary_dsn": f"postgresql://{app_user}:CHANGE_ME@{args.primary_host}:{args.primary_port}/{database_name}",
        "artifacts": [
            {"kind": "pgbouncer_ini", "path": str(ini_path)},
            {"kind": "userlist_example", "path": str(userlist_path)},
            {"kind": "compose", "path": str(compose_path)},
            {"kind": "commands", "path": str(commands_path)},
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
