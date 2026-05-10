-- Local-dev bootstrap. Runs once on first container start (empty PGDATA).
--
CREATE ROLE exporter LOGIN PASSWORD 'exporter';
GRANT pg_monitor TO exporter;
GRANT CONNECT ON DATABASE appdb TO exporter;

\connect appdb
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
