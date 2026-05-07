#!/usr/bin/env bash
set -euo pipefail

PATRONI_CONFIG="${PATRONI_CONFIG:-patroni-primary.yml}"

patronictl -c "$PATRONI_CONFIG" list
patronictl -c "$PATRONI_CONFIG" switchover --master pg-primary --candidate pg-replica --force
patronictl -c "$PATRONI_CONFIG" failover --candidate pg-replica --force
curl -fsS "http://127.0.0.1:8008/cluster"
curl -fsS "http://127.0.0.1:8009/cluster"
