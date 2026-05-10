#!/bin/bash
#
# Runs as part of docker-entrypoint-initdb.d on first boot, before init.sql.
# The official postgres image's pg_hba.conf only opens `replication` to local
# unix sockets; allow it from the compose network so postgres-replica's
# pg_basebackup / walreceiver can connect with the `replicator` role.
set -euo pipefail

echo "host replication replicator 0.0.0.0/0 md5" >> "${PGDATA}/pg_hba.conf"
echo "host replication replicator ::/0        md5" >> "${PGDATA}/pg_hba.conf"
