// Command server runs the ToothFairy API gateway.
//
//	go run ./cmd/server            # from gateway/
//
// The gateway owns identity, case records, uploads and job scheduling; the Python ML service
// owns only the two expensive operations (image analysis, clinical advisory). Splitting them
// this way keeps ordinary request traffic — logins, history, status polling, media — off the
// process that loads multi-gigabyte vision models, and lets each side scale on its own.
package main

import (
	"context"
	"errors"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/farrelathalla/toothfairy/gateway/internal/auth"
	"github.com/farrelathalla/toothfairy/gateway/internal/config"
	"github.com/farrelathalla/toothfairy/gateway/internal/httpapi"
	"github.com/farrelathalla/toothfairy/gateway/internal/jobs"
	"github.com/farrelathalla/toothfairy/gateway/internal/mlclient"
	"github.com/farrelathalla/toothfairy/gateway/internal/store"
)

func main() {
	seedOnly := flag.Bool("seed", false, "seed demo accounts and cases, then exit")
	flag.Parse()

	if err := run(*seedOnly); err != nil {
		slog.Error("fatal", "err", err)
		os.Exit(1)
	}
}

func run(seedOnly bool) error {
	cfg := config.Load()

	// JSON in production (log aggregation), human-readable text in development.
	var handler slog.Handler = slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo})
	if !cfg.IsProduction() {
		handler = slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelDebug})
	}
	log := slog.New(handler)
	slog.SetDefault(log)

	if err := cfg.Validate(); err != nil {
		return err
	}
	if !cfg.IsProduction() && cfg.JWTSecret == config.DevJWTSecret {
		log.Warn("using the development JWT secret — set JWT_SECRET before deploying")
	}

	st, err := store.Open(cfg.DatabaseURL)
	if err != nil {
		return err
	}
	defer st.Close()

	if err := os.MkdirAll(cfg.UploadDir, 0o755); err != nil {
		return err
	}

	// Seeding is idempotent, so it runs on every boot: a fresh clone is one command from a
	// working login and a populated history.
	if result, err := st.Seed(context.Background(), cfg.SeedDir, auth.HashPassword); err != nil {
		log.Warn("seeding skipped", "err", err)
	} else if len(result.AccountsCreated) > 0 || len(result.CasesCreated) > 0 {
		log.Info("seeded demo data",
			"accounts", result.AccountsCreated, "cases", result.CasesCreated)
	}
	if seedOnly {
		log.Info("seed complete")
		return nil
	}

	// A process that died mid-analysis leaves cases stuck "running" forever; clear them so
	// the UI shows an honest failure the doctor can retry.
	if n, err := st.ResetStaleJobs(context.Background()); err != nil {
		log.Warn("could not reset stale jobs", "err", err)
	} else if n > 0 {
		log.Warn("reset interrupted analyses", "count", n)
	}

	ml := mlclient.New(cfg.MLBaseURL, cfg.InternalKey, cfg.MLTimeout)
	runner := jobs.NewRunner(st, ml, cfg.UploadDir, cfg.MLTimeout, log)
	runner.Start(cfg.JobWorkers, cfg.JobQueueSize)

	server := &http.Server{
		Addr:    cfg.Addr,
		Handler: httpapi.NewServer(cfg, st, auth.NewIssuer(cfg.JWTSecret, cfg.JWTTTL), ml, runner, log).Handler(),
		// No WriteTimeout: an analysis-triggered response is fast, but /media serves large
		// images over slow mobile links and a blanket write deadline would truncate them.
		ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	errCh := make(chan error, 1)
	go func() {
		log.Info("gateway listening", "config", cfg.String())
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)

	select {
	case err := <-errCh:
		return err
	case sig := <-stop:
		log.Info("shutting down", "signal", sig.String())
	}

	// Stop accepting connections first, then let in-flight analyses finish: killing a job
	// mid-run would leave a half-written results directory.
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := server.Shutdown(ctx); err != nil {
		log.Warn("http shutdown", "err", err)
	}
	runner.Shutdown(ctx)
	log.Info("stopped")
	return nil
}
