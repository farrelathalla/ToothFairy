// Package config loads the gateway's settings from the environment.
//
// Every value has a development-friendly default so `go run ./cmd/server` works with no
// setup, but the two that must never keep their defaults in production — the JWT signing
// secret and the internal API key — are reported by Validate so a misconfigured deployment
// fails loudly at boot instead of quietly serving forgeable tokens.
package config

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// DevJWTSecret is the placeholder that Validate refuses to accept outside development.
const DevJWTSecret = "dev-secret-change-me"

type Config struct {
	Env  string // "development" | "production"
	Addr string

	DatabaseURL string        // path to the SQLite file
	UploadDir   string        // raw patient photos, served at /media
	ResultsDir  string        // inference output, shared with the web app
	SeedDir     string        // demo accounts/cases used by the seeder
	JWTSecret   string        //
	JWTTTL      time.Duration //

	MLBaseURL     string        // the Python ML service
	MLTimeout     time.Duration // per analyze/advisory call
	InternalKey   string        // presented to the ML service on every internal call
	JobWorkers    int           // concurrent case runs
	JobQueueSize  int           //
	CORSOrigins   []string      //
	MaxUploadMB   int64         // per file
	RateLimitRPM  int           // per client IP, 0 = disabled
	TrustedProxy  bool          // honour X-Forwarded-For when behind a load balancer
	RequestTimout time.Duration // non-streaming handlers
}

func Load() Config {
	root := repoRoot()
	return Config{
		Env:  env("ENV", "development"),
		Addr: env("ADDR", ":8081"),

		DatabaseURL: env("DATABASE_URL", filepath.Join(root, "gateway", "data", "toothfairy.db")),
		UploadDir:   env("UPLOAD_DIR", filepath.Join(root, "gateway", "data", "uploads")),
		ResultsDir:  env("RESULTS_DIR", filepath.Join(root, "web", "public", "results")),
		SeedDir:     env("SEED_DIR", filepath.Join(root, "assets", "seed")),
		JWTSecret:   env("JWT_SECRET", DevJWTSecret),
		JWTTTL:      time.Duration(envInt("JWT_EXPIRE_MIN", 720)) * time.Minute,

		MLBaseURL:     env("ML_BASE_URL", "http://localhost:8000"),
		MLTimeout:     time.Duration(envInt("ML_TIMEOUT_S", 1800)) * time.Second,
		InternalKey:   env("INTERNAL_API_KEY", ""),
		JobWorkers:    envInt("JOB_WORKERS", 2),
		JobQueueSize:  envInt("JOB_QUEUE_SIZE", 64),
		CORSOrigins:   splitCSV(env("CORS_ORIGINS", "http://localhost:3000")),
		MaxUploadMB:   int64(envInt("MAX_UPLOAD_MB", 12)),
		RateLimitRPM:  envInt("RATE_LIMIT_RPM", 240),
		TrustedProxy:  envBool("TRUSTED_PROXY", false),
		RequestTimout: time.Duration(envInt("REQUEST_TIMEOUT_S", 30)) * time.Second,
	}
}

func (c Config) IsProduction() bool { return strings.EqualFold(c.Env, "production") }

// Validate refuses to start a production process with development secrets.
func (c Config) Validate() error {
	if !c.IsProduction() {
		return nil
	}
	var problems []string
	if c.JWTSecret == DevJWTSecret || len(c.JWTSecret) < 32 {
		problems = append(problems, "JWT_SECRET must be set to at least 32 random bytes")
	}
	if c.InternalKey == "" {
		problems = append(problems, "INTERNAL_API_KEY must be set so the ML service can reject strangers")
	}
	if len(problems) > 0 {
		return errors.New("invalid production configuration: " + strings.Join(problems, "; "))
	}
	return nil
}

// repoRoot walks up from the working directory looking for the repository markers, so the
// server can be started from either the repo root or gateway/.
func repoRoot() string {
	wd, err := os.Getwd()
	if err != nil {
		return "."
	}
	for dir := wd; ; {
		if isDir(filepath.Join(dir, "web")) && isDir(filepath.Join(dir, "ml")) {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return wd
		}
		dir = parent
	}
}

func isDir(p string) bool {
	info, err := os.Stat(p)
	return err == nil && info.IsDir()
}

func env(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return fallback
}

func envInt(key string, fallback int) int {
	if v, ok := os.LookupEnv(key); ok {
		if n, err := strconv.Atoi(strings.TrimSpace(v)); err == nil {
			return n
		}
	}
	return fallback
}

func envBool(key string, fallback bool) bool {
	if v, ok := os.LookupEnv(key); ok {
		if b, err := strconv.ParseBool(strings.TrimSpace(v)); err == nil {
			return b
		}
	}
	return fallback
}

func splitCSV(s string) []string {
	var out []string
	for _, part := range strings.Split(s, ",") {
		if p := strings.TrimSpace(part); p != "" {
			out = append(out, p)
		}
	}
	return out
}

func (c Config) String() string {
	return fmt.Sprintf("env=%s addr=%s ml=%s workers=%d db=%s",
		c.Env, c.Addr, c.MLBaseURL, c.JobWorkers, c.DatabaseURL)
}
