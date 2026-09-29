// Package middleware holds the cross-cutting HTTP concerns: request identity, structured
// logging, panic recovery, CORS, security headers, body-size limits and rate limiting.
//
// They compose in a fixed order (see httpapi.Router): recovery outermost so it catches
// everything, then request id and logging so every line is correlatable, then the
// security-relevant limits.
package middleware

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"log/slog"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

type ctxKey string

const requestIDKey ctxKey = "request_id"

// Chain applies middleware so that the first argument is the outermost wrapper.
func Chain(h http.Handler, mw ...func(http.Handler) http.Handler) http.Handler {
	for i := len(mw) - 1; i >= 0; i-- {
		h = mw[i](h)
	}
	return h
}

func RequestIDFrom(ctx context.Context) string {
	id, _ := ctx.Value(requestIDKey).(string)
	return id
}

// RequestID attaches a correlation id, preferring one an upstream proxy already set.
func RequestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get("X-Request-ID")
		if id == "" || len(id) > 64 {
			buf := make([]byte, 8)
			_, _ = rand.Read(buf)
			id = hex.EncodeToString(buf)
		}
		w.Header().Set("X-Request-ID", id)
		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), requestIDKey, id)))
	})
}

type statusWriter struct {
	http.ResponseWriter
	status int
	bytes  int
}

func (w *statusWriter) WriteHeader(code int) {
	w.status = code
	w.ResponseWriter.WriteHeader(code)
}

func (w *statusWriter) Write(b []byte) (int, error) {
	if w.status == 0 {
		w.status = http.StatusOK
	}
	n, err := w.ResponseWriter.Write(b)
	w.bytes += n
	return n, err
}

// Flush keeps streaming responses working through the wrapper.
func (w *statusWriter) Flush() {
	if f, ok := w.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

// Logger records one structured line per request. It deliberately logs the **path only** —
// never the query string or body — because case ids and patient names must not end up in
// log aggregation.
func Logger(log *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			sw := &statusWriter{ResponseWriter: w}
			next.ServeHTTP(sw, r)

			if sw.status == 0 {
				sw.status = http.StatusOK
			}
			level := slog.LevelInfo
			if sw.status >= 500 {
				level = slog.LevelError
			} else if sw.status >= 400 {
				level = slog.LevelWarn
			}
			log.Log(r.Context(), level, "request",
				"method", r.Method,
				"path", r.URL.Path,
				"status", sw.status,
				"bytes", sw.bytes,
				"duration_ms", time.Since(start).Milliseconds(),
				"request_id", RequestIDFrom(r.Context()),
			)
		})
	}
}

// Recover turns a panic into a 500 instead of a dropped connection, and never leaks the
// panic value to the client.
func Recover(log *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				if p := recover(); p != nil {
					log.Error("panic recovered", "path", r.URL.Path, "panic", p,
						"request_id", RequestIDFrom(r.Context()))
					w.Header().Set("Content-Type", "application/json; charset=utf-8")
					w.WriteHeader(http.StatusInternalServerError)
					_, _ = w.Write([]byte(`{"detail":"Terjadi kesalahan internal"}`))
				}
			}()
			next.ServeHTTP(w, r)
		})
	}
}

// CORS reflects only origins on the allow list. A wildcard is never emitted, because the API
// is called with credentials and `*` is both invalid and dangerous in that mode.
func CORS(allowed []string) func(http.Handler) http.Handler {
	set := make(map[string]bool, len(allowed))
	for _, o := range allowed {
		set[strings.TrimRight(o, "/")] = true
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			origin := strings.TrimRight(r.Header.Get("Origin"), "/")
			if origin != "" && set[origin] {
				h := w.Header()
				h.Set("Access-Control-Allow-Origin", origin)
				h.Set("Access-Control-Allow-Credentials", "true")
				h.Set("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Request-ID")
				h.Set("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
				h.Set("Access-Control-Max-Age", "600")
				h.Add("Vary", "Origin")
			}
			if r.Method == http.MethodOptions {
				w.WriteHeader(http.StatusNoContent)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// SecurityHeaders sets the defensive defaults that apply to an API serving JSON and images.
func SecurityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h := w.Header()
		h.Set("X-Content-Type-Options", "nosniff")
		h.Set("X-Frame-Options", "DENY")
		h.Set("Referrer-Policy", "no-referrer")
		h.Set("Cross-Origin-Resource-Policy", "cross-origin")
		// Patient media must never be cached by a shared proxy.
		if strings.HasPrefix(r.URL.Path, "/media/") {
			h.Set("Cache-Control", "private, no-store")
		}
		next.ServeHTTP(w, r)
	})
}

// MaxBody caps the request body so an upload cannot exhaust memory or disk.
func MaxBody(limit int64) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			r.Body = http.MaxBytesReader(w, r.Body, limit)
			next.ServeHTTP(w, r)
		})
	}
}

// ClientIP resolves the caller's address, honouring X-Forwarded-For **only** when the
// deployment says it is behind a trusted proxy — otherwise any client could spoof the header
// and walk straight past the rate limiter.
func ClientIP(r *http.Request, trustProxy bool) string {
	if trustProxy {
		if fwd := r.Header.Get("X-Forwarded-For"); fwd != "" {
			if first, _, ok := strings.Cut(fwd, ","); ok {
				return strings.TrimSpace(first)
			}
			return strings.TrimSpace(fwd)
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

// RateLimiter is a fixed-window counter per client IP. Deliberately simple: the goal is to
// blunt credential stuffing and accidental polling storms, not to be a CDN.
type RateLimiter struct {
	limit      int
	window     time.Duration
	trustProxy bool

	mu      sync.Mutex
	hits    map[string]*counter
	lastGC  time.Time
	nowFunc func() time.Time
}

type counter struct {
	count int
	reset time.Time
}

func NewRateLimiter(perMinute int, trustProxy bool) *RateLimiter {
	return &RateLimiter{
		limit: perMinute, window: time.Minute, trustProxy: trustProxy,
		hits: map[string]*counter{}, nowFunc: time.Now,
	}
}

// Allow reports whether this client may proceed, and how long until the window resets.
func (rl *RateLimiter) Allow(key string) (bool, time.Duration) {
	if rl.limit <= 0 {
		return true, 0
	}
	now := rl.nowFunc()

	rl.mu.Lock()
	defer rl.mu.Unlock()

	if now.Sub(rl.lastGC) > 5*rl.window {
		for k, c := range rl.hits {
			if now.After(c.reset) {
				delete(rl.hits, k)
			}
		}
		rl.lastGC = now
	}

	c, ok := rl.hits[key]
	if !ok || now.After(c.reset) {
		rl.hits[key] = &counter{count: 1, reset: now.Add(rl.window)}
		return true, 0
	}
	c.count++
	if c.count > rl.limit {
		return false, time.Until(c.reset)
	}
	return true, 0
}

func (rl *RateLimiter) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ok, retryAfter := rl.Allow(ClientIP(r, rl.trustProxy))
		if !ok {
			w.Header().Set("Retry-After", strconv.Itoa(int(retryAfter.Seconds())+1))
			w.Header().Set("Content-Type", "application/json; charset=utf-8")
			w.WriteHeader(http.StatusTooManyRequests)
			_, _ = w.Write([]byte(`{"detail":"Terlalu banyak permintaan, coba lagi sebentar lagi"}`))
			return
		}
		next.ServeHTTP(w, r)
	})
}
