#!/usr/bin/env bash
set -euo pipefail

APP_DSN="${APP_DSN:-postgresql://seccomp:CHANGE_ME@pgbouncer:6432/seccomp_metadata}"
ADMIN_DSN="${ADMIN_DSN:-postgresql://pgbouncer_admin:CHANGE_ME@pgbouncer:6432/pgbouncer}"
DIRECT_PRIMARY_DSN="${DIRECT_PRIMARY_DSN:-postgresql://seccomp:CHANGE_ME@pg-primary:5432/seccomp_metadata}"

psql "$APP_DSN" -c "SELECT 1;"
psql "$ADMIN_DSN" -c "SHOW POOLS;"
psql "$ADMIN_DSN" -c "SHOW STATS;"

# Long write transactions such as apply-registry should use this direct
# primary DSN or a separate pgBouncer session-mode listener.
python3 scripts/manage_metadata_db.py --db-dsn "$DIRECT_PRIMARY_DSN" status
python3 scripts/benchmark_read_adapters.py --db-dsn "$APP_DSN" --iterations 1
