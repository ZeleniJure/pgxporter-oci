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
//     PGX_DB       — database to connect to
//     PGX_PASSWORD       — optional; if set, password auth is used instead of RDS IAM
//     AWS_REGION         — required in IAM mode (SigV4 signing)
//     LISTEN_ADDR        — defaults to ":9187"
//     PGX_METRIC_PREFIX  — "pg_stat" (default, native pgxporter / modern names
//     matching the bundled Grafana dashboards) or "pg"
//     (postgres_exporter-compat: pg_database_*, pg_bgwriter_*, …)
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
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
	database := mustEnv(log, "PGX_DB")
	port := envIntDefault(log, "PGX_PORT", defaultPort)
	listenAddr := envDefault("LISTEN_ADDR", defaultListenAddr)
	password := os.Getenv("PGX_PASSWORD")
	metricPrefix, err := parseMetricPrefix(os.Getenv("PGX_METRIC_PREFIX"))
	if err != nil {
		log.Error("invalid PGX_METRIC_PREFIX", "err", err)
		os.Exit(2)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer cancel()

	dbOpts := db.Opts{
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
		log.Info("auth mode: password")
		dbOpts.Password = password
	} else {
		// IAM mode: mint a fresh SigV4-signed token per connection via
		// pgx's BeforeConnect hook. Pool connections are rotated under
		// the 15-minute token TTL.
		region := mustEnv(log, "AWS_REGION")
		log.Info("auth mode: rds-iam", "region", region)
		provider, err := awsrds.NewDefault(ctx, region)
		if err != nil {
			log.Error("init AWS RDS auth provider", "err", err)
			os.Exit(1)
		}
		dbOpts.AuthProvider = provider
		dbOpts.PoolMaxConnLifetime = poolConnLifetime
	}

	exp, err := exporter.New(ctx, exporter.Opts{
		// MetricPrefix selects the metric namespace. Default is
		// "pg_stat" (native pgxporter / modern names — what the
		// bundled Grafana dashboards in local/grafana/dashboards
		// expect). Set PGX_METRIC_PREFIX=pg for postgres_exporter
		// dashboard-name compatibility (pg_database_*, pg_bgwriter_*).
		MetricPrefix: metricPrefix,
		DBOpts:       []db.Opts{dbOpts},
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
		log.Info("listening", "addr", listenAddr, "host", host, "user", user, "db", database)
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

func envDefault(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return fallback
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
