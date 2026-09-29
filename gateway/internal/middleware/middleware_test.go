package middleware

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func ok(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) }

func TestChainAppliesTheFirstMiddlewareOutermost(t *testing.T) {
	var order []string
	mark := func(name string) func(http.Handler) http.Handler {
		return func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				order = append(order, name)
				next.ServeHTTP(w, r)
			})
		}
	}
	handler := Chain(http.HandlerFunc(ok), mark("first"), mark("second"))
	handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))

	if len(order) != 2 || order[0] != "first" || order[1] != "second" {
		t.Errorf("execution order = %v", order)
	}
}

func TestRecoverTurnsAPanicIntoA500WithoutLeakingIt(t *testing.T) {
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	handler := Recover(log)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		panic("secret internal detail")
	}))

	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/", nil))

	if rec.Code != http.StatusInternalServerError {
		t.Errorf("status = %d", rec.Code)
	}
	if body := rec.Body.String(); contains(body, "secret internal detail") {
		t.Errorf("panic value leaked to the client: %s", body)
	}
}

func TestRequestIDIsGeneratedAndEchoed(t *testing.T) {
	var seen string
	handler := RequestID(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = RequestIDFrom(r.Context())
	}))

	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/", nil))
	if seen == "" || rec.Header().Get("X-Request-ID") != seen {
		t.Errorf("generated id = %q, header = %q", seen, rec.Header().Get("X-Request-ID"))
	}
}

func TestRequestIDPrefersAnUpstreamValue(t *testing.T) {
	var seen string
	handler := RequestID(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = RequestIDFrom(r.Context())
	}))

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("X-Request-ID", "upstream-123")
	handler.ServeHTTP(httptest.NewRecorder(), req)

	if seen != "upstream-123" {
		t.Errorf("id = %q", seen)
	}
}

func TestMaxBodyRejectsAnOversizedRequest(t *testing.T) {
	handler := MaxBody(16)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, err := io.ReadAll(r.Body); err != nil {
			w.WriteHeader(http.StatusRequestEntityTooLarge)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/", io.LimitReader(zeroReader{}, 1024))
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Errorf("status = %d", rec.Code)
	}
}

type zeroReader struct{}

func (zeroReader) Read(p []byte) (int, error) { return len(p), nil }

func TestRateLimiterAllowsUpToTheLimitThenRefuses(t *testing.T) {
	rl := NewRateLimiter(3, false)
	for i := 0; i < 3; i++ {
		if allowed, _ := rl.Allow("1.2.3.4"); !allowed {
			t.Fatalf("request %d refused inside the limit", i+1)
		}
	}
	if allowed, retry := rl.Allow("1.2.3.4"); allowed || retry <= 0 {
		t.Errorf("fourth request allowed=%v retry=%v", allowed, retry)
	}
	// A different client has its own budget.
	if allowed, _ := rl.Allow("5.6.7.8"); !allowed {
		t.Error("an unrelated client was rate limited")
	}
}

func TestRateLimiterWindowResets(t *testing.T) {
	rl := NewRateLimiter(1, false)
	base := time.Now()
	rl.nowFunc = func() time.Time { return base }

	rl.Allow("1.2.3.4")
	if allowed, _ := rl.Allow("1.2.3.4"); allowed {
		t.Fatal("second request in the window was allowed")
	}
	rl.nowFunc = func() time.Time { return base.Add(2 * time.Minute) }
	if allowed, _ := rl.Allow("1.2.3.4"); !allowed {
		t.Error("the window never reset")
	}
}

func TestRateLimiterDisabledWhenLimitIsZero(t *testing.T) {
	rl := NewRateLimiter(0, false)
	for i := 0; i < 100; i++ {
		if allowed, _ := rl.Allow("1.2.3.4"); !allowed {
			t.Fatal("a disabled limiter refused a request")
		}
	}
}

func TestClientIPIgnoresForwardedHeaderUnlessProxyIsTrusted(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.RemoteAddr = "10.0.0.1:5555"
	req.Header.Set("X-Forwarded-For", "1.1.1.1, 2.2.2.2")

	// Untrusted: a client could otherwise spoof its way around the rate limiter.
	if got := ClientIP(req, false); got != "10.0.0.1" {
		t.Errorf("untrusted = %q, want the socket address", got)
	}
	if got := ClientIP(req, true); got != "1.1.1.1" {
		t.Errorf("trusted = %q, want the first forwarded hop", got)
	}
}

func TestCORSNeverEmitsAWildcardAndSkipsUnknownOrigins(t *testing.T) {
	handler := CORS([]string{"http://localhost:3000"})(http.HandlerFunc(ok))

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Origin", "https://evil.example")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Errorf("unknown origin allowed: %q", got)
	}

	req = httptest.NewRequest(http.MethodOptions, "/", nil)
	req.Header.Set("Origin", "http://localhost:3000")
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusNoContent {
		t.Errorf("preflight status = %d", rec.Code)
	}
	if rec.Header().Get("Access-Control-Allow-Origin") == "*" {
		t.Error("wildcard origin emitted on a credentialed API")
	}
}

func TestSecurityHeadersMarkPatientMediaAsNoStore(t *testing.T) {
	handler := SecurityHeaders(http.HandlerFunc(ok))

	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/media/case-1/up.jpg", nil))
	if cc := rec.Header().Get("Cache-Control"); cc != "private, no-store" {
		t.Errorf("media Cache-Control = %q", cc)
	}

	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/cases", nil))
	if cc := rec.Header().Get("Cache-Control"); cc != "" {
		t.Errorf("non-media Cache-Control = %q", cc)
	}
}

func contains(haystack, needle string) bool { return strings.Contains(haystack, needle) }
