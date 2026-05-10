#!/bin/bash
#
# Synthetic workload for the local stack. Two concurrent generators:
#
#   1. pgbench  -- TPC-B-ish OLTP. Drives xact rate, WAL, bgwriter,
#                  checkpoints, buffer hit/miss ratios.
#   2. psql loop -- application-shaped INSERT/UPDATE/SELECT/DELETE on
#                  demo.widgets so pg_stat_user_tables and
#                  pg_stat_statements show recognizable per-table /
#                  per-query metrics (not just pgbench_*).
#
# Tuned to be visible on dashboards but not saturate a laptop.
set -euo pipefail

echo "loadgen: initializing pgbench (scale=10)..."
pgbench -i -s 10 -q

echo "loadgen: starting pgbench (4 clients, 2 threads, indefinite)..."
pgbench -c 4 -j 2 -T 0 -P 30 --no-vacuum &
PGBENCH_PID=$!

# Forward SIGTERM/SIGINT to pgbench so `docker compose stop` is clean.
trap 'kill -TERM "$PGBENCH_PID" 2>/dev/null || true; exit 0' TERM INT

echo "loadgen: starting demo.widgets workload..."
while true; do
    psql -v ON_ERROR_STOP=1 -q <<'SQL'
        -- Reads
        SELECT count(*) FROM demo.widgets WHERE qty > 50;
        SELECT id, name, qty FROM demo.widgets ORDER BY updated_at DESC LIMIT 25;
        SELECT avg(qty)::int FROM demo.widgets;

        -- Writes
        INSERT INTO demo.widgets (name, qty)
        SELECT 'widget-' || (random() * 1e9)::bigint, (random() * 100)::int
        FROM generate_series(1, 20);

        UPDATE demo.widgets
           SET qty = qty + 1, updated_at = now()
         WHERE id IN (SELECT id FROM demo.widgets ORDER BY random() LIMIT 50);

        DELETE FROM demo.widgets
         WHERE id IN (SELECT id FROM demo.widgets ORDER BY random() LIMIT 10);
SQL
    sleep 1
done
