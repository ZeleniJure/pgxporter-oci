# Local development recipes for pgxporter-oci.
#
# Install just: https://github.com/casey/just
#   cargo install just     # or: brew install just / apt install just
#
# Quickstart:
#   just up
#   just metrics

set shell := ["bash", "-cu"]

# Default target: list available recipes.
default:
    @just --list

# Build images and start the full stack (postgres + replica + exporter x2 + prometheus + grafana).
up:
    docker compose up -d --build
    @echo
    @echo "  pgxporter (primary)  http://localhost:9187/metrics"
    @echo "  pgxporter (replica)  http://localhost:9188/metrics"
    @echo "  prometheus           http://localhost:9090"
    @echo "  grafana              http://localhost:3000"
    @echo
    @echo "  primary psql:  just psql           (localhost:5432)"
    @echo "  replica psql:  just psql-replica   (localhost:5433, read-only)"
    @echo "  load gen:      just load           (pgbench + demo.widgets)"

# Stop the stack, keep volumes.
down:
    docker compose down

# Stop and drop all volumes (fresh DB, fresh Prometheus TSDB, fresh Grafana).
nuke:
    docker compose down -v

# Tail logs. Optionally pass a service: `just logs pgxporter`.
logs svc="":
    docker compose logs -f --tail=200 {{svc}}

# Rebuild only the exporter image and recreate the container. Use after editing main.go / Dockerfile.
rebuild:
    docker compose build pgxporter
    docker compose up -d --no-deps pgxporter
    docker compose logs -f --tail=50 pgxporter

# Run the exporter from source against the compose Postgres. Fastest inner loop, no Docker rebuild.
# Requires `just up` to have been run at least once (so postgres is reachable on localhost:5432).
run:
    PGX_HOST=localhost \
    PGX_PORT=5432 \
    PGX_USER=exporter \
    PGX_PASSWORD=exporter \
    PGX_DB=appdb \
    LISTEN_ADDR=":9187" \
    go run .

# Open an interactive psql shell inside the postgres container as the superuser.
psql:
    docker compose exec postgres psql -U postgres -d appdb

# Open an interactive psql shell against the replica (read-only). Useful for
# confirming standby state, e.g. `SELECT pg_is_in_recovery();` or
# `SELECT * FROM pg_stat_wal_receiver;`.
psql-replica:
    docker compose exec postgres-replica psql -U postgres -d appdb

# Start the synthetic workload generator (pgbench + demo.widgets loop).
# Profile-gated so it doesn't run by default. Tail its output with
# `just logs pgbench`.
load:
    docker compose --profile load up -d pgbench
    @echo "loadgen running. stop it with 'just load-stop', tail with 'just logs pgbench'."

# Stop the workload generator without tearing down the rest of the stack.
load-stop:
    docker compose stop pgbench
    docker compose rm -f pgbench

# Run a single SQL query and print the result. Quote the whole query.
#   just sql "SHOW shared_preload_libraries;"
#   just sql "SELECT extname FROM pg_extension;"
sql QUERY:
    docker compose exec -T postgres psql -U postgres -d appdb -c {{quote(QUERY)}}

# Curl the exporter and page through the metrics output.
metrics:
    curl -fsS http://localhost:9187/metrics | less

# Open the Prometheus UI.
prom:
    xdg-open http://localhost:9090 2>/dev/null || open http://localhost:9090

# Open the Grafana UI.
grafana:
    xdg-open http://localhost:3000 2>/dev/null || open http://localhost:3000

# Go housekeeping.
fmt:
    gofmt -s -w .

vet:
    go vet ./...

tidy:
    go mod tidy

# Build the binary locally (no Docker), useful sanity check before committing.
build:
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o ./bin/pgxporter .
