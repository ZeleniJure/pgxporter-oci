#!/bin/bash
#
# Tiny always-on activity generator. One trivial query per second is enough
# to keep pg_stat_database.xact_commit, pg_stat_database.tup_returned and a
# couple of pg_stat_statements rows ticking, so dashboards on a fresh
# `just up` don't look broken (everything flatlined at zero).
#
# This is deliberately *not* the heavy `loadgen.sh` workload: no writes, no
# data growth, no measurable CPU/IO. Run `just load` for the real workload.
set -euo pipefail

# Wait for the primary to be reachable; the compose healthcheck covers this
# but we may still race on first boot if depends_on isn't enough.
until pg_isready -q; do sleep 1; done

while true; do
    psql -v ON_ERROR_STOP=0 -At -q >/dev/null <<'SQL' || true
        SELECT 1;
        SELECT count(*) FROM demo.widgets;
        SELECT now();
SQL
    sleep 1
done
