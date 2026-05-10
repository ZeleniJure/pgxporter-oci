#!/bin/bash
#
# Standby bootstrap. On first boot PGDATA is empty -> stream a fresh base
# backup from the primary (which also writes standby.signal via -R), then
# delegate to the stock entrypoint. On subsequent boots PGDATA is already
# populated and we skip straight to startup.
set -euo pipefail

if [ -z "$(ls -A "$PGDATA" 2>/dev/null || true)" ]; then
    echo "replica: PGDATA empty, running pg_basebackup against primary..."

    # Wait for the primary to accept replication connections. The compose
    # healthcheck only proves SQL is up; the walsender path can lag a moment.
    until PGPASSWORD=replicator pg_isready -h postgres -U replicator -d postgres -q; do
        echo "replica: waiting for primary..."
        sleep 1
    done

    PGPASSWORD=replicator pg_basebackup \
        --host=postgres \
        --username=replicator \
        --pgdata="$PGDATA" \
        --format=plain \
        --wal-method=stream \
        --write-recovery-conf \
        --slot=replica1 \
        --progress \
        --verbose

    chmod 0700 "$PGDATA"
    echo "replica: base backup complete"
fi

# Hand off to the stock entrypoint so it sets up sockets, signals, etc.
exec docker-entrypoint.sh postgres
