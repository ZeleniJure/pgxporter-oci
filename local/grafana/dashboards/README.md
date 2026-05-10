# Dashboards

Three Grafana dashboards are auto-loaded by the provisioning config in
`../provisioning/dashboards/dashboards.yaml`:

| File | Source | Purpose |
| --- | --- | --- |
| `pgxporter-health.json` | **Official**, vendored from [becomeliminal/pgxporter `dashboards/`](https://github.com/becomeliminal/pgxporter/tree/main/dashboards) | Exporter self-observability — scrape duration / errors / cardinality per collector. |
| `pgxporter-overview.json` | Custom (this repo) | One-screen Postgres health: connections, TPS, cache hit, replication lag, WAL rate. |
| `pgxporter-postgres.json` | Custom (this repo) | Full-featured per-subsystem deep dive: activity, throughput, cache & I/O, locks, WAL, checkpointer, replication, storage, top-N tables. |

## Regenerating dashboards

The two custom dashboards are generated from `_build_dashboards.py` —
edit the script, re-run it, commit the resulting JSON. Panels are
authored against the metric names this exporter actually emits (default
`PGX_METRIC_PREFIX=pg_stat`, native pgxporter naming), so they do **not**
require flipping to the `postgres_exporter`-compat prefix.

> The script is fully vibe-coded

```bash
python3 local/grafana/dashboards/_build_dashboards.py
```

Stdlib-only, no deps.
