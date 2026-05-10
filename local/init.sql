-- Local-dev bootstrap. Runs once on first container start (empty PGDATA).
--
CREATE ROLE exporter LOGIN PASSWORD 'exporter';
GRANT pg_monitor TO exporter;
GRANT CONNECT ON DATABASE appdb TO exporter;

-- Streaming-replication role + physical slot consumed by postgres-replica.
-- The slot keeps WAL around for the standby across restarts so a brief
-- replica outage doesn't force a re-basebackup.
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replicator';
SELECT pg_create_physical_replication_slot('replica1');

\connect appdb
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Demo schema for the load generator. Having a real application-shaped
-- table makes pg_stat_user_tables / pg_stat_statements light up with
-- recognizable queries instead of only pgbench's tpcb_* ones.
CREATE SCHEMA demo;
CREATE TABLE demo.widgets (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL,
    qty         int  NOT NULL DEFAULT 0,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX widgets_updated_at_idx ON demo.widgets (updated_at);
INSERT INTO demo.widgets (name, qty)
SELECT 'widget-' || g, (random() * 100)::int
FROM generate_series(1, 1000) g;

GRANT USAGE ON SCHEMA demo TO exporter;
GRANT SELECT ON ALL TABLES IN SCHEMA demo TO exporter;
