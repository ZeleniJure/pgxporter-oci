# pgxporter image

Tiny Go wrapper around [`becomeliminal/pgxporter`](https://github.com/becomeliminal/pgxporter)
that wires its `awsrds` AuthProvider so the exporter authenticates to RDS via
IAM (no password, no Secrets Manager).

## Configuration

Environment variables (no flags, no config file):

| Variable     | Required | Default | Notes |
| ------------ | -------- | ------- | ----- |
| `PGX_HOST`   | yes      |         | RDS endpoint (writer or reader) |
| `PGX_PORT`   | no       | `5432`  | |
| `PGX_USER`   | yes      |         | Postgres role. In IAM mode it must have `GRANT rds_iam`. |
| `PGX_DB`     | yes      |         | Comma-separated list of databases (e.g. `appdb` or `appdb,analytics`). One pgxpool is opened per database; cluster-wide views are only collected once (rows are tagged with `current_database()` so labels don't collide), but per-database views (`pg_stat[io]_user_tables`, `pg_stat[io]_user_indexes`, `pg_stat_progress_*`) are scoped to the connected DB and so are only emitted for the databases you list here. |
| `PGX_PASSWORD` | no     |         | If set, password auth is used and AWS is **not** consulted. Intended for local dev / non-RDS deployments. |
| `AWS_REGION` | conditional |      | Required in IAM mode (when `PGX_PASSWORD` is empty). Used for SigV4 token signing. |
| `LISTEN_ADDR`| no       | `:9187` | |
| `PGX_METRIC_PREFIX` | no | `pg_stat` | Metric namespace. `pg_stat` (default) — native pgxporter / modern PostgreSQL view names (`pg_stat_database_*`, `pg_stat_bgwriter_*`, …), matching the bundled Grafana dashboards. `pg` — drop-in compatibility with community `postgres_exporter` dashboards (`pg_database_*`, `pg_bgwriter_*`, …). |
| `PGX_ENABLE_COLLECTORS`  | no |     | Comma-separated. If set, restricts the running collector set to exactly these names; overrides the default-enabled set. Use to opt into collectors that are off by default (`statements`, `settings`, `subscription`) without pulling every other collector along. |
| `PGX_DISABLE_COLLECTORS` | no |     | Comma-separated. Subtracted from the resolved collector set after `PGX_ENABLE_COLLECTORS`, so a name in both lists ends up disabled. Use on managed Postgres flavours that hide certain views (see [Managed Postgres / Aurora](#managed-postgres--aurora) below). Unknown names are logged and ignored — a typo on deploy won't take the exporter down. |

Auth mode is chosen at startup and logged (`auth mode: password` or
`auth mode: rds-iam`). In IAM mode the container picks up AWS credentials from
the standard chain — on Fargate that resolves to the ECS task role via the
metadata endpoint. The task role only needs `rds-db:connect` on the dbuser ARN.

`MetricPrefix` defaults to `MetricPrefixPgStat` — native pgxporter naming
(`pg_stat_database_*`, `pg_stat_bgwriter_*`, …) which matches the modern
PostgreSQL view names and the Grafana dashboards bundled under
`local/grafana/dashboards/`. Set `PGX_METRIC_PREFIX=pg` to switch to the
`postgres_exporter`-compatible naming (`pg_database_*`, `pg_bgwriter_*`, …)
if you want to reuse community `postgres_exporter` Grafana dashboards
unchanged.

`PoolMaxConnLifetime` is 14 minutes — RDS IAM tokens are valid 15 minutes, so
pgxpool rotates connections one minute before expiry and every fresh
connection gets a freshly minted token.

### Collectors

The full collector list lives in the upstream
[`exporter/collectors`](https://pkg.go.dev/github.com/becomeliminal/pgxporter/exporter/collectors)
package. As of `v1.0.0-rc2`:

```
activity, archiver, bgwriter, checkpointer, database, database_size,
io, io_user_indexes, io_user_tables, locks,
progress_analyze, progress_basebackup, progress_cluster, progress_copy,
progress_create_index, progress_vacuum,
replication, replication_slots, settings, slru, ssl, statements,
subscription, user_indexes, user_tables, wal, wal_receiver
```

Default-on is everything **except** `settings`, `statements`,
`subscription` (high cardinality / niche / expensive).

#### Managed Postgres / Aurora

Managed flavours often restrict access to certain system views and the
exporter will log a per-scrape error for each one. Disable them
explicitly to keep logs clean:

```bash
# Aurora writer (typical):
PGX_DISABLE_COLLECTORS=wal_receiver,slru,subscription

# Aurora reader (no replication state at all):
PGX_DISABLE_COLLECTORS=wal_receiver,slru,subscription,replication,replication_slots
```

`PGX_ENABLE_COLLECTORS` is the inverse knob — pin the running set to
exactly the listed names, e.g. opt into `statements` without enabling
`settings`:

```bash
PGX_ENABLE_COLLECTORS=database,database_size,activity,bgwriter,wal,statements
```

If both are set, `PGX_DISABLE_COLLECTORS` wins for any name in both
lists.

## Local development

A full stack (Postgres + this exporter + Prometheus + Grafana) is wired
up via `compose.yaml` and driven by [`just`](https://github.com/casey/just).

Prerequisites: Docker (with the compose plugin), `just`, and Go if you
want to run the binary outside Docker.

```bash
just up         # build images + start the stack
just metrics    # curl the exporter
just logs pgxporter
just down       # stop (keep volumes)
just nuke       # stop + drop volumes (fresh DB next time)
```

Endpoints once the stack is up:

| Service             | URL                                      | Notes |
| ------------------- | ---------------------------------------- | ----- |
| Exporter (primary)  | <http://localhost:9187/metrics>          | also `/healthz` |
| Exporter (replica)  | <http://localhost:9188/metrics>          | scrapes the standby |
| Prometheus          | <http://localhost:9090>                  | scrapes both exporters every 15s |
| Grafana             | <http://localhost:3000>                  | anonymous Admin, login form disabled |
| Postgres (primary)  | `localhost:5432`                         | user `exporter` / pass `exporter` / db `appdb` |
| Postgres (replica)  | `localhost:5433`                         | streaming standby, read-only |

In the compose stack `pgxporter` runs in **password mode** (`PGX_PASSWORD` is
set), so no AWS credentials are needed. The `exporter` Postgres role is
created by `local/init.sql` with `pg_monitor` membership.

### Replica & load generator

The stack ships with a streaming physical replica and an opt-in workload
generator so the dashboards aren't a wall of zeros:

- `postgres-replica` runs `pg_basebackup` against the primary on first boot
  (using the `replicator` role and the `replica1` physical slot created in
  `local/init.sql`) and then streams WAL via the standard walreceiver. It
  exposes 5433 on the host. A second exporter, `pgxporter-replica`, scrapes
  it on `:9188`. Prometheus tags the two with `role={primary,replica}` and
  `instance={local-pg17-primary,local-pg17-replica}`.
  - Sanity check: `just psql-replica` then
    `SELECT pg_is_in_recovery();` (`t`),
    `SELECT * FROM pg_stat_wal_receiver;` (one row).
  - On the primary: `SELECT application_name, state, sync_state,
    pg_wal_lsn_diff(sent_lsn, replay_lsn) AS lag_bytes
    FROM pg_stat_replication;`.

- `pgpoke` runs always-on and fires one trivial read-only query per second
  (`SELECT 1`, `SELECT count(*) FROM demo.widgets`, `SELECT now()`) so a
  fresh `just up` doesn't show flatlined-at-zero dashboards. It's
  deliberately tiny — no writes, no data growth, no measurable CPU/IO.

- `just load` brings up the `pgbench` service (compose profile `load`),
  which runs `pgbench -c 4 -j 2 -T 0` against `appdb` *and* a parallel
  psql loop hammering `demo.widgets` with mixed SELECT/INSERT/UPDATE/DELETE.
  This lights up `pg_stat_database`, `pg_stat_user_tables`,
  `pg_stat_bgwriter`, WAL/checkpoint counters and `pg_stat_statements`.
  Stop it with `just load-stop`; the rest of the stack keeps running.

### Inner loops

- **Iterating on `main.go` without rebuilding the image** — run the binary
  from source against the compose Postgres:

  ```bash
  just up      # only needed once, to bring Postgres up
  just run     # go run . with the right env vars baked in
  ```

- **Iterating on the `Dockerfile`** — rebuild and recreate just the exporter
  container, leaving Postgres / Prometheus / Grafana untouched:

  ```bash
  just rebuild
  ```

- **Poking at the database** — `just psql` drops you into a `psql` shell as
  `postgres` inside the container.

### Other recipes

`just --list` shows all of them. Useful extras: `just fmt`, `just vet`,
`just tidy`, `just build` (compile the binary into `./bin/` without Docker).

