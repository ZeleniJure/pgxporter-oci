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
| `PGX_DB`     | yes      |         | e.g. `yeet` |
| `PGX_PASSWORD` | no     |         | If set, password auth is used and AWS is **not** consulted. Intended for local dev / non-RDS deployments. |
| `AWS_REGION` | conditional |      | Required in IAM mode (when `PGX_PASSWORD` is empty). Used for SigV4 token signing. |
| `LISTEN_ADDR`| no       | `:9187` | |
| `PGX_METRIC_PREFIX` | no | `pg_stat` | Metric namespace. `pg_stat` (default) — native pgxporter / modern PostgreSQL view names (`pg_stat_database_*`, `pg_stat_bgwriter_*`, …), matching the bundled Grafana dashboards. `pg` — drop-in compatibility with community `postgres_exporter` dashboards (`pg_database_*`, `pg_bgwriter_*`, …). |

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

| Service    | URL                                      | Notes |
| ---------- | ---------------------------------------- | ----- |
| Exporter   | <http://localhost:9187/metrics>          | also `/healthz` |
| Prometheus | <http://localhost:9090>                  | scrapes the exporter every 15s |
| Grafana    | <http://localhost:3000>                  | anonymous Admin, login form disabled |
| Postgres   | `localhost:5432`                         | user `exporter` / pass `exporter` / db `appdb` |

In the compose stack `pgxporter` runs in **password mode** (`PGX_PASSWORD` is
set), so no AWS credentials are needed. The `exporter` Postgres role is
created by `local/init.sql` with `pg_monitor` membership.

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

