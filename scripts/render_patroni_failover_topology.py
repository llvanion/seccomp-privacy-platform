#!/usr/bin/env python3
import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_ID = "patroni_failover_topology_report/v1"
SERVICE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require_service_name(value: str, *, field_name: str) -> str:
    candidate = str(value or "").strip()
    if not SERVICE_NAME_RE.match(candidate):
        raise ValueError(f"{field_name} must match {SERVICE_NAME_RE.pattern}")
    return candidate


def render_patroni_config(
    *,
    scope: str,
    node_name: str,
    node_service: str,
    etcd_service: str,
    restapi_port: int,
    postgres_port: int,
    superuser_name: str,
    replication_user: str,
    ttl: int,
    loop_wait: int,
    retry_timeout: int,
    maximum_lag_on_failover: int,
) -> str:
    return f"""scope: {scope}
namespace: /service/
name: {node_name}

restapi:
  listen: 0.0.0.0:8008
  connect_address: {node_service}:{restapi_port}

etcd3:
  hosts: {etcd_service}:2379

bootstrap:
  dcs:
    ttl: {ttl}
    loop_wait: {loop_wait}
    retry_timeout: {retry_timeout}
    maximum_lag_on_failover: {maximum_lag_on_failover}
    postgresql:
      use_pg_rewind: true
      use_slots: true
      parameters:
        wal_level: replica
        hot_standby: "on"
        max_wal_senders: 10
        max_replication_slots: 10
  initdb:
    - encoding: UTF8
    - data-checksums
  pg_hba:
    - host replication {replication_user} 0.0.0.0/0 scram-sha-256
    - host all all 0.0.0.0/0 scram-sha-256

postgresql:
  listen: 0.0.0.0:5432
  connect_address: {node_service}:{postgres_port}
  data_dir: /var/lib/postgresql/data
  authentication:
    replication:
      username: {replication_user}
      password: CHANGE_ME_REPLICATION_PASSWORD
    superuser:
      username: {superuser_name}
      password: CHANGE_ME_SUPERUSER_PASSWORD
  parameters:
    unix_socket_directories: /var/run/postgresql

tags:
  nofailover: false
  noloadbalance: false
  clonefrom: false
  nosync: false
"""


def render_compose(
    *,
    project_name: str,
    patroni_image: str,
    etcd_image: str,
    primary_service: str,
    replica_service: str,
    etcd_service: str,
    primary_postgres_port: int,
    replica_postgres_port: int,
    primary_restapi_port: int,
    replica_restapi_port: int,
) -> str:
    return f"""name: {project_name}
services:
  {etcd_service}:
    image: {etcd_image}
    restart: unless-stopped
    command:
      - /usr/local/bin/etcd
      - --name
      - {etcd_service}
      - --data-dir
      - /etcd-data
      - --initial-advertise-peer-urls
      - http://{etcd_service}:2380
      - --listen-peer-urls
      - http://0.0.0.0:2380
      - --advertise-client-urls
      - http://{etcd_service}:2379
      - --listen-client-urls
      - http://0.0.0.0:2379
      - --initial-cluster
      - {etcd_service}=http://{etcd_service}:2380
      - --initial-cluster-state
      - new
      - --initial-cluster-token
      - seccomp-postgres-ha
    volumes:
      - patroni-etcd-data:/etcd-data

  {primary_service}:
    image: {patroni_image}
    restart: unless-stopped
    command: ["patroni", "/etc/patroni/patroni.yml"]
    volumes:
      - ./patroni-primary.yml:/etc/patroni/patroni.yml:ro
      - patroni-primary-data:/var/lib/postgresql/data
    depends_on:
      - {etcd_service}
    ports:
      - "{primary_postgres_port}:5432"
      - "{primary_restapi_port}:8008"

  {replica_service}:
    image: {patroni_image}
    restart: unless-stopped
    command: ["patroni", "/etc/patroni/patroni.yml"]
    volumes:
      - ./patroni-replica.yml:/etc/patroni/patroni.yml:ro
      - patroni-replica-data:/var/lib/postgresql/data
    depends_on:
      - {etcd_service}
      - {primary_service}
    ports:
      - "{replica_postgres_port}:5432"
      - "{replica_restapi_port}:8008"

volumes:
  patroni-etcd-data:
  patroni-primary-data:
  patroni-replica-data:
"""


def render_commands(primary_config_path: str, primary_service: str, replica_service: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

PATRONI_CONFIG="${{PATRONI_CONFIG:-{primary_config_path}}}"

patronictl -c "$PATRONI_CONFIG" list
patronictl -c "$PATRONI_CONFIG" switchover --master {primary_service} --candidate {replica_service} --force
patronictl -c "$PATRONI_CONFIG" failover --candidate {replica_service} --force
curl -fsS "http://127.0.0.1:8008/cluster"
curl -fsS "http://127.0.0.1:8009/cluster"
"""


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def validate_text_artifacts(
    *,
    primary_config: str,
    replica_config: str,
    compose_text: str,
    commands_text: str,
    scope: str,
    primary_service: str,
    replica_service: str,
    etcd_service: str,
    maximum_lag_on_failover: int,
) -> list[dict[str, Any]]:
    checks = [
        ("primary_scope", f"scope: {scope}" in primary_config),
        ("replica_scope", f"scope: {scope}" in replica_config),
        ("primary_restapi", f"connect_address: {primary_service}:8008" in primary_config),
        ("replica_restapi", f"connect_address: {replica_service}:8009" in replica_config),
        ("etcd3_backend", f"hosts: {etcd_service}:2379" in primary_config and f"hosts: {etcd_service}:2379" in replica_config),
        ("failover_timing", all(token in primary_config for token in ["ttl: 30", "loop_wait: 10", "retry_timeout: 10"])),
        ("maximum_lag_on_failover", f"maximum_lag_on_failover: {maximum_lag_on_failover}" in primary_config),
        ("pg_rewind_enabled", "use_pg_rewind: true" in primary_config),
        ("replication_slots_enabled", "use_slots: true" in primary_config),
        ("wal_replica_params", all(token in primary_config for token in ["wal_level: replica", "max_wal_senders", "max_replication_slots"])),
        ("scram_pg_hba", "scram-sha-256" in primary_config and "host replication" in primary_config),
        ("compose_etcd_service", f"  {etcd_service}:" in compose_text and "listen-client-urls" in compose_text),
        ("compose_patroni_nodes", f"  {primary_service}:" in compose_text and f"  {replica_service}:" in compose_text),
        ("compose_patroni_command", 'command: ["patroni", "/etc/patroni/patroni.yml"]' in compose_text),
        ("compose_restapi_ports", '"8008:8008"' in compose_text and '"8009:8008"' in compose_text),
        ("commands_patronictl_list", 'patronictl -c "$PATRONI_CONFIG" list' in commands_text),
        ("commands_switchover", "switchover" in commands_text and f"--candidate {replica_service}" in commands_text),
        ("commands_failover", "failover" in commands_text and f"--candidate {replica_service}" in commands_text),
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
    ap = argparse.ArgumentParser(description="Render Patroni automated failover topology artifacts for metadata PostgreSQL.")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--output", default="", help="Optional report JSON output path")
    ap.add_argument("--project-name", default="seccomp-patroni-ha")
    ap.add_argument("--scope", default="seccomp-privacy")
    ap.add_argument("--patroni-image", default="ghcr.io/zalando/spilo-16:3.2-p3")
    ap.add_argument("--etcd-image", default="quay.io/coreos/etcd:v3.5.15")
    ap.add_argument("--superuser-name", default="postgres")
    ap.add_argument("--replication-user", default="replicator")
    ap.add_argument("--primary-service", default="pg-primary")
    ap.add_argument("--replica-service", default="pg-replica")
    ap.add_argument("--etcd-service", default="etcd")
    ap.add_argument("--primary-postgres-port", type=int, default=5432)
    ap.add_argument("--replica-postgres-port", type=int, default=5433)
    ap.add_argument("--primary-restapi-port", type=int, default=8008)
    ap.add_argument("--replica-restapi-port", type=int, default=8009)
    ap.add_argument("--ttl", type=int, default=30)
    ap.add_argument("--loop-wait", type=int, default=10)
    ap.add_argument("--retry-timeout", type=int, default=10)
    ap.add_argument("--maximum-lag-on-failover", type=int, default=1048576)
    ap.add_argument("--docker-compose-config", action="store_true", help="Run 'docker compose config' when Docker is available")
    ap.add_argument("--assert-ok", action="store_true")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    try:
        primary_service = require_service_name(args.primary_service, field_name="primary_service")
        replica_service = require_service_name(args.replica_service, field_name="replica_service")
        etcd_service = require_service_name(args.etcd_service, field_name="etcd_service")
        if len({primary_service, replica_service, etcd_service}) != 3:
            raise ValueError("primary_service, replica_service, and etcd_service must differ")
        for field_name in ("primary_postgres_port", "replica_postgres_port", "primary_restapi_port", "replica_restapi_port"):
            if getattr(args, field_name) <= 0:
                raise ValueError(f"{field_name} must be positive")
        if len({args.primary_postgres_port, args.replica_postgres_port}) != 2:
            raise ValueError("primary and replica PostgreSQL ports must differ")
        if len({args.primary_restapi_port, args.replica_restapi_port}) != 2:
            raise ValueError("primary and replica REST API ports must differ")
        if args.ttl <= 0 or args.loop_wait <= 0 or args.retry_timeout <= 0:
            raise ValueError("Patroni timing values must be positive")
        if args.maximum_lag_on_failover <= 0:
            raise ValueError("maximum_lag_on_failover must be positive")
    except ValueError as exc:
        raise SystemExit(f"[ERROR] {exc}") from exc

    out_dir = Path(args.out_dir).resolve()
    primary_path = out_dir / "patroni-primary.yml"
    replica_path = out_dir / "patroni-replica.yml"
    compose_path = out_dir / "docker-compose.patroni.yml"
    commands_path = out_dir / "patroni_failover_commands.sh"

    primary_config = render_patroni_config(
        scope=args.scope,
        node_name=primary_service,
        node_service=primary_service,
        etcd_service=etcd_service,
        restapi_port=args.primary_restapi_port,
        postgres_port=args.primary_postgres_port,
        superuser_name=args.superuser_name,
        replication_user=args.replication_user,
        ttl=args.ttl,
        loop_wait=args.loop_wait,
        retry_timeout=args.retry_timeout,
        maximum_lag_on_failover=args.maximum_lag_on_failover,
    )
    replica_config = render_patroni_config(
        scope=args.scope,
        node_name=replica_service,
        node_service=replica_service,
        etcd_service=etcd_service,
        restapi_port=args.replica_restapi_port,
        postgres_port=args.replica_postgres_port,
        superuser_name=args.superuser_name,
        replication_user=args.replication_user,
        ttl=args.ttl,
        loop_wait=args.loop_wait,
        retry_timeout=args.retry_timeout,
        maximum_lag_on_failover=args.maximum_lag_on_failover,
    )
    compose_text = render_compose(
        project_name=args.project_name,
        patroni_image=args.patroni_image,
        etcd_image=args.etcd_image,
        primary_service=primary_service,
        replica_service=replica_service,
        etcd_service=etcd_service,
        primary_postgres_port=args.primary_postgres_port,
        replica_postgres_port=args.replica_postgres_port,
        primary_restapi_port=args.primary_restapi_port,
        replica_restapi_port=args.replica_restapi_port,
    )
    commands_text = render_commands(
        primary_config_path="patroni-primary.yml",
        primary_service=primary_service,
        replica_service=replica_service,
    )

    write_text(primary_path, primary_config)
    write_text(replica_path, replica_config)
    write_text(compose_path, compose_text)
    write_text(commands_path, commands_text)

    checks = validate_text_artifacts(
        primary_config=primary_config,
        replica_config=replica_config,
        compose_text=compose_text,
        commands_text=commands_text,
        scope=args.scope,
        primary_service=primary_service,
        replica_service=replica_service,
        etcd_service=etcd_service,
        maximum_lag_on_failover=args.maximum_lag_on_failover,
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
        "scope": args.scope,
        "primary_service": primary_service,
        "replica_service": replica_service,
        "etcd_service": etcd_service,
        "patroni_image": args.patroni_image,
        "etcd_image": args.etcd_image,
        "maximum_lag_on_failover": args.maximum_lag_on_failover,
        "artifacts": [
            {"kind": "compose", "path": str(compose_path)},
            {"kind": "primary_config", "path": str(primary_path)},
            {"kind": "replica_config", "path": str(replica_path)},
            {"kind": "failover_commands", "path": str(commands_path)},
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
