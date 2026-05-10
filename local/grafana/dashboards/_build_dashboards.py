#!/usr/bin/env python3
"""
Generates the two pgxporter dashboards in this directory.

Why a generator instead of hand-edited JSON:
  - Grafana panel JSON is verbose (~80 lines per panel). Hand-writing
    20+ panels twice is a copy-paste minefield where one wrong refId
    quietly breaks a panel.
  - Every panel here shares the same datasource / templating / units
    conventions. Centralising those in helpers is the only way to keep
    the two dashboards consistent.
  - The output is regenerated, not edited. Tweak this script, run it,
    commit the resulting JSON.

Usage:
    python3 _build_dashboards.py

All metric names below were verified against a live exporter
(`curl localhost:9187/metrics`) on 2026-05-10 — see the Prometheus
label-values dump used to author this. If a panel says "No data" after
a metric rename upstream, the fix lives here.
"""
from __future__ import annotations

import json
import pathlib

DS = {"type": "prometheus", "uid": "${DS_PROMETHEUS}"}
HERE = pathlib.Path(__file__).parent


def target(expr: str, legend: str = "", ref: str = "A", instant: bool = False) -> dict:
    return {
        "datasource": DS,
        "expr": expr,
        "legendFormat": legend,
        "refId": ref,
        "instant": instant,
    }


def panel(
    pid: int,
    title: str,
    targets: list[dict],
    *,
    ptype: str = "timeseries",
    unit: str = "short",
    gp: tuple[int, int, int, int] = (0, 0, 12, 8),
    decimals: int | None = None,
    description: str = "",
    overrides: list | None = None,
    options: dict | None = None,
    min_: float | None = None,
    max_: float | None = None,
) -> dict:
    x, y, w, h = gp
    custom: dict = {"drawStyle": "line", "lineInterpolation": "linear",
                    "fillOpacity": 10, "showPoints": "never", "spanNulls": False}
    defaults: dict = {"unit": unit, "custom": custom, "color": {"mode": "palette-classic"}}
    if decimals is not None:
        defaults["decimals"] = decimals
    if min_ is not None:
        defaults["min"] = min_
    if max_ is not None:
        defaults["max"] = max_

    p = {
        "id": pid,
        "type": ptype,
        "title": title,
        "description": description,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": options or {
            "legend": {"displayMode": "table", "placement": "bottom",
                       "calcs": ["lastNotNull", "max"]},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }
    return p


def stat(pid, title, expr, *, unit="short", gp=(0, 0, 4, 4), decimals=0,
         color_mode="value", thresholds=None, description=""):
    defaults = {
        "unit": unit,
        "decimals": decimals,
        "color": {"mode": "thresholds"},
        "thresholds": thresholds or {
            "mode": "absolute",
            "steps": [{"color": "green", "value": None}],
        },
    }
    return {
        "id": pid,
        "type": "stat",
        "title": title,
        "description": description,
        "datasource": DS,
        "gridPos": {"x": gp[0], "y": gp[1], "w": gp[2], "h": gp[3]},
        "targets": [target(expr, instant=True)],
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "colorMode": color_mode,
            "graphMode": "area",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
            "orientation": "auto",
        },
    }


def row(pid, title, y) -> dict:
    return {
        "id": pid, "type": "row", "title": title, "collapsed": False,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": [],
    }


def templating(extras: list[dict] | None = None) -> dict:
    base = [
        {
            "current": {"text": "Prometheus", "value": "prometheus"},
            "hide": 0, "includeAll": False, "label": "Datasource",
            "name": "DS_PROMETHEUS", "options": [], "query": "prometheus",
            "refresh": 1, "regex": "", "skipUrlSync": False, "type": "datasource",
        },
        {
            "current": {"text": "All", "value": "$__all"},
            "datasource": DS,
            "definition": "label_values(pg_stat_up, job)",
            "hide": 0, "includeAll": True, "label": "job", "multi": True,
            "name": "job", "options": [],
            "query": {"query": "label_values(pg_stat_up, job)", "refId": "StandardVariableQuery"},
            "refresh": 2, "regex": "", "skipUrlSync": False, "sort": 1, "type": "query",
        },
        {
            "current": {"text": "All", "value": "$__all"},
            "datasource": DS,
            "definition": 'label_values(pg_stat_up{job=~"$job"}, instance)',
            "hide": 0, "includeAll": True, "label": "instance", "multi": True,
            "name": "instance", "options": [],
            "query": {"query": 'label_values(pg_stat_up{job=~"$job"}, instance)',
                      "refId": "StandardVariableQuery"},
            "refresh": 2, "regex": "", "skipUrlSync": False, "sort": 1, "type": "query",
        },
        {
            "current": {"text": "All", "value": "$__all"},
            "datasource": DS,
            "definition": ('label_values(pg_stat_database_numbackends'
                           '{job=~"$job", instance=~"$instance"}, datname)'),
            "hide": 0, "includeAll": True, "label": "datname", "multi": True,
            "name": "datname", "options": [],
            "query": {"query": ('label_values(pg_stat_database_numbackends'
                                '{job=~"$job", instance=~"$instance", datname!=""}, datname)'),
                      "refId": "StandardVariableQuery"},
            "refresh": 2, "regex": "", "skipUrlSync": False, "sort": 1, "type": "query",
        },
    ]
    return {"list": base + (extras or [])}


def dashboard(uid, title, description, panels, refresh="30s", time_from="now-1h"):
    return {
        "annotations": {"list": []},
        "description": description,
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,  # shared crosshair
        "liveNow": False,
        "panels": panels,
        "refresh": refresh,
        "schemaVersion": 38,
        "style": "dark",
        "tags": ["postgres", "pgxporter"],
        "templating": templating(),
        "time": {"from": time_from, "to": "now"},
        "timepicker": {},
        "timezone": "",
        "title": title,
        "uid": uid,
        "version": 1,
        "weekStart": "",
    }


# --------------------------------------------------------------------------
# Overview dashboard — one screen, the things you check first.
# --------------------------------------------------------------------------
# Selectors are deliberately consistent: every panel filters by
# {job=~"$job", instance=~"$instance"} so the dropdowns wired in
# templating() actually do something. Per-database panels add datname.
SEL = '{job=~"$job", instance=~"$instance"}'
SEL_DB = '{job=~"$job", instance=~"$instance", datname=~"$datname", datname!=""}'


def build_overview() -> dict:
    panels = []
    pid = 1

    # Row of stats. Up-count is the canary: if it's 0 the rest is meaningless.
    panels.append(stat(
        pid, "Exporters Up", f'sum(pg_stat_up{SEL})',
        gp=(0, 0, 4, 4), unit="short",
        thresholds={"mode": "absolute", "steps": [
            {"color": "red", "value": None}, {"color": "green", "value": 1},
        ]},
        description="Count of pgxporter instances reporting healthy.",
    )); pid += 1
    panels.append(stat(
        pid, "Connections", f'sum(pg_stat_database_numbackends{SEL_DB})',
        gp=(4, 0, 4, 4),
        description="Total backends across selected databases.",
    )); pid += 1
    panels.append(stat(
        pid, "Commits/s",
        f'sum(rate(pg_stat_database_xact_commit_total{SEL_DB}[$__rate_interval]))',
        gp=(8, 0, 4, 4), unit="ops", decimals=1,
    )); pid += 1
    panels.append(stat(
        pid, "Rollbacks/s",
        f'sum(rate(pg_stat_database_xact_rollback_total{SEL_DB}[$__rate_interval]))',
        gp=(12, 0, 4, 4), unit="ops", decimals=2,
        thresholds={"mode": "absolute", "steps": [
            {"color": "green", "value": None}, {"color": "yellow", "value": 1},
            {"color": "red", "value": 10},
        ]},
    )); pid += 1
    # Cache hit ratio: classic Postgres health check. Numerator only counts
    # heap-fetch shortcut hits; the denominator includes misses to OS/disk,
    # which is what you actually want to keep above ~0.99 for OLTP.
    panels.append(stat(
        pid, "Cache Hit Ratio",
        ('sum(rate(pg_stat_database_blks_hit_total' + SEL_DB + '[5m])) / '
         '(sum(rate(pg_stat_database_blks_hit_total' + SEL_DB + '[5m])) '
         '+ sum(rate(pg_stat_database_blks_read_total' + SEL_DB + '[5m])))'),
        gp=(16, 0, 4, 4), unit="percentunit", decimals=4, color_mode="background",
        thresholds={"mode": "absolute", "steps": [
            {"color": "red", "value": None}, {"color": "yellow", "value": 0.95},
            {"color": "green", "value": 0.99},
        ]},
    )); pid += 1
    panels.append(stat(
        pid, "Deadlocks (5m)",
        f'sum(increase(pg_stat_database_deadlocks_total{SEL_DB}[5m]))',
        gp=(20, 0, 4, 4),
        thresholds={"mode": "absolute", "steps": [
            {"color": "green", "value": None}, {"color": "red", "value": 1},
        ]},
    )); pid += 1

    # Time-series row.
    panels.append(panel(
        pid, "Transactions / sec by instance",
        [target(f'sum by (instance) (rate(pg_stat_database_xact_commit_total{SEL_DB}[$__rate_interval]))',
                "{{instance}} commit", "A"),
         target(f'sum by (instance) (rate(pg_stat_database_xact_rollback_total{SEL_DB}[$__rate_interval]))',
                "{{instance}} rollback", "B")],
        gp=(0, 4, 12, 8), unit="ops",
    )); pid += 1

    panels.append(panel(
        pid, "Connections by state",
        [target(f'sum by (state) (pg_stat_activity_count{SEL})',
                "{{state}}")],
        gp=(12, 4, 12, 8),
    )); pid += 1

    panels.append(panel(
        pid, "Tuples / sec (returned, fetched, inserted, updated, deleted)",
        [target(f'sum(rate(pg_stat_database_tup_returned_total{SEL_DB}[$__rate_interval]))', "returned", "A"),
         target(f'sum(rate(pg_stat_database_tup_fetched_total{SEL_DB}[$__rate_interval]))',  "fetched",  "B"),
         target(f'sum(rate(pg_stat_database_tup_inserted_total{SEL_DB}[$__rate_interval]))', "inserted", "C"),
         target(f'sum(rate(pg_stat_database_tup_updated_total{SEL_DB}[$__rate_interval]))',  "updated",  "D"),
         target(f'sum(rate(pg_stat_database_tup_deleted_total{SEL_DB}[$__rate_interval]))',  "deleted",  "E")],
        gp=(0, 12, 12, 8), unit="ops",
    )); pid += 1

    panels.append(panel(
        pid, "Database size",
        [target(f'pg_database_size_bytes{SEL_DB}', "{{instance}} / {{datname}}")],
        gp=(12, 12, 12, 8), unit="bytes",
    )); pid += 1

    # Replication lag: works only when a replica is connected. With no replica
    # the series is absent and Grafana renders an empty panel, which is the
    # honest answer — no fake-zero baseline.
    panels.append(panel(
        pid, "Replication lag (replay)",
        [target(f'pg_stat_replication_replay_lag_seconds{SEL}', "{{instance}} {{application_name}} s", "A"),
         target(f'pg_stat_replication_replay_lag_bytes{SEL}',   "{{instance}} {{application_name}} bytes", "B")],
        gp=(0, 20, 12, 8), unit="s",
        description="Empty if no replica is streaming. Seconds and bytes plotted on the same axis intentionally — orders of magnitude differ, switch to log scale if both are non-zero.",
    )); pid += 1

    panels.append(panel(
        pid, "WAL bytes / sec",
        [target(f'sum by (instance) (rate(pg_stat_wal_bytes_total{SEL}[$__rate_interval]))',
                "{{instance}}")],
        gp=(12, 20, 12, 8), unit="Bps",
    )); pid += 1

    return dashboard(
        uid="pgxporter-overview",
        title="pgxporter — Overview",
        description="Single-screen Postgres health: connection count, TPS, cache hit, replication lag, WAL rate. Drill into 'pgxporter — Postgres' for per-subsystem detail.",
        panels=panels,
    )


# --------------------------------------------------------------------------
# Full-featured dashboard — every collector that ships data, organised by row.
# --------------------------------------------------------------------------
def build_full() -> dict:
    panels: list[dict] = []
    y = 0
    pid = 100

    def add_row(title):
        nonlocal y, pid
        panels.append(row(pid, title, y))
        pid += 1
        y += 1

    # ----- Cluster health -------------------------------------------------
    add_row("Cluster health")
    panels.append(stat(pid, "Up", f'pg_stat_up{SEL}',
                       gp=(0, y, 4, 4),
                       thresholds={"mode": "absolute", "steps": [
                           {"color": "red", "value": None},
                           {"color": "green", "value": 1}]})); pid += 1
    panels.append(stat(pid, "Scrapes / sec",
                       f'sum(rate(pg_stat_exporter_scrapes_total{SEL}[$__rate_interval]))',
                       gp=(4, y, 4, 4), unit="ops", decimals=2)); pid += 1
    panels.append(stat(pid, "Scrape errors (5m)",
                       f'sum(increase(pg_stat_scrape_errors_total{SEL}[5m]))',
                       gp=(8, y, 4, 4),
                       thresholds={"mode": "absolute", "steps": [
                           {"color": "green", "value": None},
                           {"color": "red", "value": 1}]})); pid += 1
    panels.append(stat(pid, "Total cardinality",
                       f'sum(pg_stat_metric_cardinality{SEL})',
                       gp=(12, y, 4, 4),
                       description="Sum of per-collector emitted series. Spikes here precede Prometheus ingest pressure.")); pid += 1
    panels.append(stat(pid, "Max scrape p95 (s)",
                       'max(histogram_quantile(0.95, sum by (le, collector) '
                       f'(rate(pg_stat_scrape_duration_seconds_bucket{SEL}[5m]))))',
                       gp=(16, y, 4, 4), unit="s", decimals=3)); pid += 1
    panels.append(stat(pid, "SSL connections",
                       f'sum(pg_stat_ssl_connections{SEL})',
                       gp=(20, y, 4, 4))); pid += 1
    y += 4

    # ----- Connections & activity ----------------------------------------
    add_row("Connections & activity")
    panels.append(panel(
        pid, "Backends by state",
        [target(f'sum by (state) (pg_stat_activity_count{SEL})', "{{state}}")],
        gp=(0, y, 12, 8))); pid += 1
    panels.append(panel(
        pid, "Backends by wait_event_type",
        [target(f'sum by (wait_event_type) (pg_stat_activity_count{SEL})',
                "{{wait_event_type}}")],
        gp=(12, y, 12, 8))); pid += 1
    y += 8
    panels.append(panel(
        pid, "Max query / tx / backend age (seconds)",
        [target(f'max(pg_stat_activity_max_query_duration_seconds{SEL})', "max query", "A"),
         target(f'max(pg_stat_activity_max_tx_duration_seconds{SEL})',    "max tx",    "B"),
         target(f'max(pg_stat_activity_max_backend_age_seconds{SEL})',    "max age",   "C")],
        gp=(0, y, 12, 8), unit="s")); pid += 1
    panels.append(panel(
        pid, "Sessions: abandoned / fatal / killed (rate)",
        [target(f'sum(rate(pg_stat_database_sessions_abandoned_total{SEL_DB}[$__rate_interval]))', "abandoned", "A"),
         target(f'sum(rate(pg_stat_database_sessions_fatal_total{SEL_DB}[$__rate_interval]))',     "fatal",     "B"),
         target(f'sum(rate(pg_stat_database_sessions_killed_total{SEL_DB}[$__rate_interval]))',    "killed",    "C")],
        gp=(12, y, 12, 8), unit="ops")); pid += 1
    y += 8

    # ----- Throughput ----------------------------------------------------
    add_row("Throughput")
    panels.append(panel(
        pid, "Transactions / sec by datname",
        [target(f'sum by (datname) (rate(pg_stat_database_xact_commit_total{SEL_DB}[$__rate_interval]))',
                "{{datname}} commit", "A"),
         target(f'sum by (datname) (rate(pg_stat_database_xact_rollback_total{SEL_DB}[$__rate_interval]))',
                "{{datname}} rollback", "B")],
        gp=(0, y, 12, 8), unit="ops")); pid += 1
    panels.append(panel(
        pid, "Tuples / sec",
        [target(f'sum(rate(pg_stat_database_tup_returned_total{SEL_DB}[$__rate_interval]))', "returned", "A"),
         target(f'sum(rate(pg_stat_database_tup_fetched_total{SEL_DB}[$__rate_interval]))',  "fetched",  "B"),
         target(f'sum(rate(pg_stat_database_tup_inserted_total{SEL_DB}[$__rate_interval]))', "inserted", "C"),
         target(f'sum(rate(pg_stat_database_tup_updated_total{SEL_DB}[$__rate_interval]))',  "updated",  "D"),
         target(f'sum(rate(pg_stat_database_tup_deleted_total{SEL_DB}[$__rate_interval]))',  "deleted",  "E")],
        gp=(12, y, 12, 8), unit="ops")); pid += 1
    y += 8

    # ----- Cache & I/O ---------------------------------------------------
    add_row("Cache & I/O")
    panels.append(panel(
        pid, "Cache hit ratio (per datname)",
        [target(('sum by (datname) (rate(pg_stat_database_blks_hit_total' + SEL_DB + '[5m])) / '
                 '(sum by (datname) (rate(pg_stat_database_blks_hit_total' + SEL_DB + '[5m])) '
                 '+ sum by (datname) (rate(pg_stat_database_blks_read_total' + SEL_DB + '[5m])))'),
                "{{datname}}")],
        gp=(0, y, 12, 8), unit="percentunit", decimals=4, min_=0, max_=1)); pid += 1
    panels.append(panel(
        pid, "Block hits vs reads (sum)",
        [target(f'sum(rate(pg_stat_database_blks_hit_total{SEL_DB}[$__rate_interval]))',  "hits",  "A"),
         target(f'sum(rate(pg_stat_database_blks_read_total{SEL_DB}[$__rate_interval]))', "reads", "B")],
        gp=(12, y, 12, 8), unit="ops")); pid += 1
    y += 8
    # pg_stat_io: PG 16+. Empty on older clusters.
    # `pg_stat_io_op_bytes` is one series per (backend_type, context, object)
    # carrying the block size for that I/O path (almost always 8192). Plain
    # elementwise multiplication matches on the shared label set; aggregating
    # outside the multiplication keeps the result one line per backend_type.
    # Earlier revisions used `* on() group_left() pg_stat_io_op_bytes` which
    # tripped Prometheus' "duplicate series on the right-hand side" error.
    panels.append(panel(
        pid, "pg_stat_io — read bytes/sec by backend_type (PG 16+)",
        [target(('sum by (backend_type) ('
                 'rate(pg_stat_io_reads_total' + SEL + '[$__rate_interval]) '
                 '* pg_stat_io_op_bytes' + SEL + ')'), "{{backend_type}}")],
        gp=(0, y, 12, 8), unit="Bps",
        description="Reads/sec × op_bytes (block size, ~8192). Empty on PG < 16.")); pid += 1
    panels.append(panel(
        pid, "pg_stat_io — write bytes/sec by backend_type (PG 16+)",
        [target(('sum by (backend_type) ('
                 'rate(pg_stat_io_writes_total' + SEL + '[$__rate_interval]) '
                 '* pg_stat_io_op_bytes' + SEL + ')'), "{{backend_type}}")],
        gp=(12, y, 12, 8), unit="Bps",
        description="Writes/sec × op_bytes. Empty on PG < 16.")); pid += 1
    y += 8

    panels.append(panel(
        pid, "pg_stat_io — hit ratio by backend_type (PG 16+)",
        [target(('sum by (backend_type) (rate(pg_stat_io_hits_total' + SEL + '[5m])) / '
                 '(sum by (backend_type) (rate(pg_stat_io_hits_total' + SEL + '[5m])) '
                 '+ sum by (backend_type) (rate(pg_stat_io_reads_total' + SEL + '[5m])))'),
                "{{backend_type}}")],
        gp=(0, y, 12, 8), unit="percentunit", decimals=4, min_=0, max_=1,
        description="Per-backend buffer-cache hit ratio.")); pid += 1
    panels.append(panel(
        pid, "Temp files / sec & temp bytes / sec",
        [target(f'sum(rate(pg_stat_database_temp_files_total{SEL_DB}[$__rate_interval]))', "temp files/s", "A"),
         target(f'sum(rate(pg_stat_database_temp_bytes_total{SEL_DB}[$__rate_interval]))', "temp bytes/s", "B")],
        gp=(12, y, 12, 8), unit="ops",
        description="Non-zero indicates work_mem spilling to disk — usually a sort/hash-join the planner couldn't fit in memory.")); pid += 1
    y += 8

    # ----- Locks ---------------------------------------------------------
    add_row("Locks & contention")
    panels.append(panel(
        pid, "Locks held by mode",
        [target(f'sum by (mode) (pg_stat_locks_count{SEL})', "{{mode}}")],
        gp=(0, y, 12, 8))); pid += 1
    panels.append(panel(
        pid, "Blocked backends & blocker edges",
        [target(f'sum(pg_stat_locks_blocked_backends{SEL})', "blocked", "A"),
         target(f'sum(pg_stat_locks_blocker_edges{SEL})',    "blocker edges", "B")],
        gp=(12, y, 12, 8))); pid += 1
    y += 8
    panels.append(panel(
        pid, "Deadlocks & conflicts (5m increase)",
        [target(f'sum(increase(pg_stat_database_deadlocks_total{SEL_DB}[5m]))', "deadlocks", "A"),
         target(f'sum(increase(pg_stat_database_conflicts_total{SEL_DB}[5m]))', "conflicts", "B")],
        gp=(0, y, 24, 6))); pid += 1
    y += 6

    # ----- WAL & checkpoints --------------------------------------------
    add_row("WAL, bgwriter, checkpointer")
    panels.append(panel(
        pid, "WAL bytes / sec",
        [target(f'sum by (instance) (rate(pg_stat_wal_bytes_total{SEL}[$__rate_interval]))',
                "{{instance}}")],
        gp=(0, y, 12, 8), unit="Bps")); pid += 1
    panels.append(panel(
        pid, "WAL records & FPIs / sec",
        [target(f'sum(rate(pg_stat_wal_records_total{SEL}[$__rate_interval]))', "records", "A"),
         target(f'sum(rate(pg_stat_wal_fpi_total{SEL}[$__rate_interval]))',     "fpi",     "B"),
         target(f'sum(rate(pg_stat_wal_buffers_full_total{SEL}[$__rate_interval]))', "buffers full", "C")],
        gp=(12, y, 12, 8), unit="ops")); pid += 1
    y += 8
    panels.append(panel(
        pid, "Bgwriter buffers (alloc/clean) per sec",
        [target(f'sum(rate(pg_stat_bgwriter_buffers_alloc_total{SEL}[$__rate_interval]))', "alloc", "A"),
         target(f'sum(rate(pg_stat_bgwriter_buffers_clean_total{SEL}[$__rate_interval]))', "clean", "B"),
         target(f'sum(rate(pg_stat_bgwriter_maxwritten_clean_total{SEL}[$__rate_interval]))', "maxwritten halts", "C")],
        gp=(0, y, 12, 8), unit="ops",
        description="In PG 17+ the checkpoint/buffers-written counters moved from pg_stat_bgwriter to pg_stat_checkpointer — see the next panel.")); pid += 1
    panels.append(panel(
        pid, "Checkpointer activity (PG 17+)",
        [target(f'sum(rate(pg_stat_checkpointer_num_timed_total{SEL}[$__rate_interval]))',     "timed/s",     "A"),
         target(f'sum(rate(pg_stat_checkpointer_num_requested_total{SEL}[$__rate_interval]))', "requested/s", "B"),
         target(f'sum(rate(pg_stat_checkpointer_buffers_written_total{SEL}[$__rate_interval]))', "buffers written/s", "C"),
         target(f'sum(rate(pg_stat_checkpointer_write_time_seconds_total{SEL}[$__rate_interval]))', "write time s/s", "D"),
         target(f'sum(rate(pg_stat_checkpointer_sync_time_seconds_total{SEL}[$__rate_interval]))',  "sync time s/s",  "E")],
        gp=(12, y, 12, 8), unit="ops")); pid += 1
    y += 8

    # ----- Replication ---------------------------------------------------
    add_row("Replication")
    panels.append(panel(
        pid, "Replication lag — seconds",
        [target(f'pg_stat_replication_replay_lag_seconds{SEL}', "{{application_name}} replay", "A"),
         target(f'pg_stat_replication_write_lag_seconds{SEL}',  "{{application_name}} write",  "B"),
         target(f'pg_stat_replication_flush_lag_seconds{SEL}',  "{{application_name}} flush",  "C")],
        gp=(0, y, 12, 8), unit="s")); pid += 1
    panels.append(panel(
        pid, "Replication lag — bytes",
        [target(f'pg_stat_replication_replay_lag_bytes{SEL}', "{{application_name}} replay", "A"),
         target(f'pg_stat_replication_write_lag_bytes{SEL}',  "{{application_name}} write",  "B"),
         target(f'pg_stat_replication_flush_lag_bytes{SEL}',  "{{application_name}} flush",  "C"),
         target(f'pg_stat_replication_sent_lag_bytes{SEL}',   "{{application_name}} sent",   "D")],
        gp=(12, y, 12, 8), unit="bytes")); pid += 1
    y += 8
    panels.append(panel(
        pid, "Replication slots — active",
        [target(f'pg_replication_slots_active{SEL}', "{{slot_name}}")],
        gp=(0, y, 8, 6), unit="short", min_=0, max_=1)); pid += 1
    panels.append(panel(
        pid, "Replication slots — retained WAL bytes",
        [target(f'pg_replication_slots_retained_wal_bytes{SEL}', "{{slot_name}}")],
        gp=(8, y, 8, 6), unit="bytes",
        description="WAL the primary cannot recycle until the slot's consumer catches up. Unbounded growth here is the classic 'forgotten replication slot fills the disk' incident.")); pid += 1
    panels.append(panel(
        pid, "WAL receiver — flush vs latest_end (replica side)",
        [target(f'pg_stat_wal_receiver_flushed_lsn_bytes{SEL}',     "flushed", "A"),
         target(f'pg_stat_wal_receiver_latest_end_lsn_bytes{SEL}',  "latest end", "B"),
         target(f'pg_stat_wal_receiver_written_lsn_bytes{SEL}',     "written", "C")],
        gp=(16, y, 8, 6), unit="bytes")); pid += 1
    y += 6

    # ----- Storage -------------------------------------------------------
    add_row("Storage")
    panels.append(panel(
        pid, "Database size (bytes)",
        [target(f'pg_database_size_bytes{SEL_DB}', "{{instance}} / {{datname}}")],
        gp=(0, y, 24, 8), unit="bytes")); pid += 1
    y += 8

    # ----- Tables --------------------------------------------------------
    add_row("Tables (top-N)")
    panels.append(panel(
        pid, "Top 10 tables by dead tuples",
        [target('topk(10, pg_stat_user_tables_n_dead_tup' + SEL_DB + ')',
                "{{datname}}.{{schemaname}}.{{relname}}")],
        gp=(0, y, 12, 8))); pid += 1
    panels.append(panel(
        pid, "Top 10 tables by sequential-scan tuple reads",
        [target('topk(10, rate(pg_stat_user_tables_sequential_scan_tup_read' + SEL_DB + '[$__rate_interval]))',
                "{{datname}}.{{schemaname}}.{{relname}}")],
        gp=(12, y, 12, 8), unit="ops")); pid += 1
    y += 8
    panels.append(panel(
        pid, "Time since last (auto)vacuum (seconds)",
        [target(('time() - max by (datname, schemaname, relname) '
                 '(pg_stat_user_tables_last_autovacuum' + SEL_DB + ')'),
                "autovacuum {{datname}}.{{relname}}", "A"),
         target(('time() - max by (datname, schemaname, relname) '
                 '(pg_stat_user_tables_last_vacuum' + SEL_DB + ')'),
                "vacuum {{datname}}.{{relname}}", "B")],
        gp=(0, y, 24, 8), unit="s",
        description="Empty until a row has actually been (auto)vacuumed once. A relentlessly-rising line on a high-churn table is the canonical autovacuum-can't-keep-up signal.")); pid += 1
    y += 8

    # ----- Exporter self -------------------------------------------------
    add_row("Exporter self-metrics (see pgxporter-health.json for full detail)")
    panels.append(panel(
        pid, "Per-collector scrape p95 (s)",
        [target(('histogram_quantile(0.95, sum by (le, collector) '
                 f'(rate(pg_stat_scrape_duration_seconds_bucket{SEL}[5m])))'),
                "{{collector}}")],
        gp=(0, y, 12, 8), unit="s")); pid += 1
    panels.append(panel(
        pid, "Per-collector cardinality",
        [target(f'pg_stat_metric_cardinality{SEL}', "{{collector}}")],
        gp=(12, y, 12, 8))); pid += 1
    y += 8

    return dashboard(
        uid="pgxporter-postgres",
        title="pgxporter — Postgres (full)",
        description="Full-featured dashboard covering every collector pgxporter ships data for: activity, throughput, cache, locks, WAL, checkpointer, replication, storage, tables, exporter self-metrics.",
        panels=panels,
        time_from="now-3h",
    )


def write(name, doc):
    path = HERE / name
    path.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {path} ({len(doc['panels'])} panels)")


if __name__ == "__main__":
    write("pgxporter-overview.json", build_overview())
    write("pgxporter-postgres.json", build_full())
