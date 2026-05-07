#!/usr/bin/env bash
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
