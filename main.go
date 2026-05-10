// Wrapper around github.com/becomeliminal/pgxporter Prometheus exporter binary
//
// Configuration is environment-only. Two auth modes are supported:
//
//   - Password mode (local dev / non-RDS deployments):
//     set PGX_PASSWORD. AWS_REGION is not required.
//
//   - RDS IAM mode (production):
//     leave PGX_PASSWORD unset. Requires AWS_REGION; the role specified by
//     PGX_USER must have GRANT rds_iam.
//
//     PGX_HOST     — Postgres host / RDS cluster endpoint
//     PGX_PORT     — defaults to 5432
//     PGX_USER     — Postgres role
//     PGX_DB       — comma-separated list of databases to connect to. The
//     exporter opens an independent pgxpool per database and
//     scrapes them concurrently. Cluster-wide views
//     (pg_stat_bgwriter, pg_stat_activity, …) are tagged with
//     current_database() upstream so labels don't collide; the
//     reason for >1 entry is the per-database views
//     (pg_stat[io]_user_tables, pg_stat[io]_user_indexes,
//     pg_stat_progress_*) which only expose the *currently
//     connected* database's rows. List every DB whose per-table
//     metrics you care about.
//     PGX_PASSWORD       — optional; if set, password auth is used instead of RDS IAM
//     AWS_REGION         — required in IAM mode (SigV4 signing)
//     LISTEN_ADDR        — defaults to ":9187"
//     PGX_METRIC_PREFIX  — "pg_stat" (default, native pgxporter / modern names
//     matching the bundled Grafana dashboards) or "pg"
//     (postgres_exporter-compat: pg_database_*, pg_bgwriter_*, …)
//     PGX_ENABLE_COLLECTORS  — optional, comma-separated. If set, restricts the
//     running collector set to exactly these names; overrides the default-
//     enabled set. Use to opt into collectors that are off by default
//     (e.g. "statements", "settings", "subscription") without pulling in
//     every other collector.
//     PGX_DISABLE_COLLECTORS — optional, comma-separated. Subtracted from the
//     resolved collector set after PGX_ENABLE_COLLECTORS, so a name in
//     both lists ends up disabled. Use on managed Postgres flavours that
//     restrict access to certain views — Aurora notably hides
//     pg_stat_wal_receiver, pg_stat_replication on the writer, the SLRU
//     view, and a few others; setting e.g.
//     PGX_DISABLE_COLLECTORS=wal_receiver,slru,subscription silences the
//     resulting scrape errors. Unknown names are logged and ignored.
//     See https://pkg.go.dev/github.com/becomeliminal/pgxporter/exporter/collectors
//     for the full list of collector names.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/prometheus/client_golang/prometheus/promhttp"

	"github.com/becomeliminal/pgxporter/exporter"
	"github.com/becomeliminal/pgxporter/exporter/collectors"
	"github.com/becomeliminal/pgxporter/exporter/db"
	"github.com/becomeliminal/pgxporter/exporter/db/auth/awsrds"
)

const (
	defaultPort       = 5432
	defaultListenAddr = ":9187"
	// RDS IAM tokens are valid 15 minutes. Rotate pgxpool connections one
	// minute before that so every fresh connection gets a token with
	// headroom. Per-connection token minting is via pgx BeforeConnect.
	poolConnLifetime = 14 * time.Minute
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))

	host := mustEnv(log, "PGX_HOST")
	user := mustEnv(log, "PGX_USER")
	databases := mustEnvList(log, "PGX_DB")
	port := envIntDefault(log, "PGX_PORT", defaultPort)
	listenAddr := envDefault("LISTEN_ADDR", defaultListenAddr)
	password := os.Getenv("PGX_PASSWORD")
	metricPrefix, err := parseMetricPrefix(os.Getenv("PGX_METRIC_PREFIX"))
	if err != nil {
		log.Error("invalid PGX_METRIC_PREFIX", "err", err)
		os.Exit(2)
	}
	// Collector enable/disable lists are optional. Validation (unknown
	// names) happens inside collectors.ResolveCollectors, which logs and
	// ignores unknown entries rather than aborting — typo-on-deploy
	// shouldn't take the exporter down. We intentionally don't validate
	// here so behaviour stays consistent with the upstream library.
	enableCollectors := envList("PGX_ENABLE_COLLECTORS")
	disableCollectors := envList("PGX_DISABLE_COLLECTORS")

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer cancel()

	// Auth is configured once and shared across every per-database pool:
	// password mode reuses the same static password, IAM mode reuses a
	// single AuthProvider (one AWS SDK client, one credential chain) that
	// mints tokens per-connection regardless of target database.
	var authProvider *awsrds.Provider
	if password != "" {
		log.Info("auth mode: password")
	} else {
		region := mustEnv(log, "AWS_REGION")
		log.Info("auth mode: rds-iam", "region", region)
		provider, err := awsrds.NewDefault(ctx, region)
		if err != nil {
			log.Error("init AWS RDS auth provider", "err", err)
			os.Exit(1)
		}
		authProvider = provider
	}

	dbOptsList := make([]db.Opts, 0, len(databases))
	for _, database := range databases {
		opts := db.Opts{
			Host:            host,
			Port:            port,
			User:            user,
			Database:        database,
			ApplicationName: "pgxporter",
			// The library's struct-tag defaults are only applied when its
			// flag/env parser is used; constructing Opts directly leaves
			// these at zero, which pgxpool either rejects (pool_max_conns)
			// or panics on (pool_health_check_period -> NewTicker(0)).
			PoolMaxConns:          2,
			PoolMinConns:          0,
			PoolMaxConnIdleTime:   30 * time.Minute,
			PoolHealthCheckPeriod: time.Minute,
		}
		if password != "" {
			// Password mode: local dev or non-RDS deployments. AWS_REGION is
			// not consulted; pgxpool uses the static password directly.
			opts.Password = password
		} else {
			// IAM mode: mint a fresh SigV4-signed token per connection via
			// pgx's BeforeConnect hook. Pool connections are rotated under
			// the 15-minute token TTL.
			opts.AuthProvider = authProvider
			opts.PoolMaxConnLifetime = poolConnLifetime
		}
		dbOptsList = append(dbOptsList, opts)
	}

	exp, err := exporter.New(ctx, exporter.Opts{
		// MetricPrefix selects the metric namespace. Default is
		// "pg_stat" (native pgxporter / modern names — what the
		// bundled Grafana dashboards in local/grafana/dashboards
		// expect). Set PGX_METRIC_PREFIX=pg for postgres_exporter
		// dashboard-name compatibility (pg_database_*, pg_bgwriter_*).
		MetricPrefix:       metricPrefix,
		DBOpts:             dbOptsList,
		EnabledCollectors:  enableCollectors,
		DisabledCollectors: disableCollectors,
	})
	if err != nil {
		log.Error("create exporter", "err", err)
		os.Exit(1)
	}
	exp.Register()

	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.Handler())
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	srv := &http.Server{
		Addr:              listenAddr,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		log.Info("listening", "addr", listenAddr, "host", host, "user", user, "dbs", databases)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("http listen", "err", err)
			cancel()
		}
	}()

	<-ctx.Done()
	log.Info("shutdown signal received")

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer shutdownCancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Error("http shutdown", "err", err)
	}
	if err := exp.Shutdown(shutdownCtx); err != nil {
		log.Error("exporter shutdown", "err", err)
	}
}

func mustEnv(log *slog.Logger, key string) string {
	v, ok := os.LookupEnv(key)
	if !ok || v == "" {
		log.Error("missing required env var", "key", key)
		os.Exit(2)
	}
	return v
}

// mustEnvList parses a comma-separated env var into a deduplicated, order-
// preserving list of non-empty values. Whitespace around entries is trimmed
// so `PGX_DB=appdb, analytics ,reporting` works the obvious way. Exits if
// the variable is missing or yields zero entries.
func mustEnvList(log *slog.Logger, key string) []string {
	raw := mustEnv(log, key)
	parts := strings.Split(raw, ",")
	out := make([]string, 0, len(parts))
	seen := make(map[string]struct{}, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		if _, dup := seen[p]; dup {
			continue
		}
		seen[p] = struct{}{}
		out = append(out, p)
	}
	if len(out) == 0 {
		log.Error("env var has no non-empty entries", "key", key, "value", raw)
		os.Exit(2)
	}
	return out
}

func envDefault(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return fallback
}

// envList parses a comma-separated env var into a deduplicated, order-
// preserving list of non-empty values. Whitespace around entries is trimmed.
// Unlike mustEnvList, missing/empty input returns nil rather than exiting —
// this is the right shape for optional knobs like PGX_ENABLE_COLLECTORS,
// where "unset" means "use library defaults".
func envList(key string) []string {
	raw := os.Getenv(key)
	if raw == "" {
		return nil
	}
	parts := strings.Split(raw, ",")
	out := make([]string, 0, len(parts))
	seen := make(map[string]struct{}, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		if _, dup := seen[p]; dup {
			continue
		}
		seen[p] = struct{}{}
		out = append(out, p)
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

func envIntDefault(log *slog.Logger, key string, fallback int) int {
	raw, ok := os.LookupEnv(key)
	if !ok || raw == "" {
		return fallback
	}
	n, err := strconv.Atoi(raw)
	if err != nil || n <= 0 || n > 65535 {
		log.Error("invalid int env var", "key", key, "value", raw, "err", err)
		os.Exit(2)
	}
	return n
}

// parseMetricPrefix maps PGX_METRIC_PREFIX to a collectors.MetricPrefix.
//
// Default (empty) is MetricPrefixPgStat — the native pgxporter naming
// (pg_stat_database_*, pg_stat_bgwriter_*, …) which matches the modern
// Postgres view names and the Grafana dashboards bundled under
// local/grafana/dashboards.
//
// "pg" selects MetricPrefixPg for drop-in compatibility with community
// postgres_exporter Grafana dashboards (pg_database_*, pg_bgwriter_*, …).
func parseMetricPrefix(raw string) (collectors.MetricPrefix, error) {
	switch raw {
	case "", "pg_stat", "pgstat", "stat":
		return collectors.MetricPrefixPgStat, nil
	case "pg", "postgres_exporter", "compat":
		return collectors.MetricPrefixPg, nil
	default:
		return "", errors.New("expected one of: pg_stat (default), pg")
	}
}
