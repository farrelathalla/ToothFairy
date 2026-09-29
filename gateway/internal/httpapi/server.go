// Package httpapi is the gateway's public HTTP surface: authentication, accounts, cases,
// uploads and the media mount. Everything expensive is delegated — image analysis and the
// clinical advisory go to the ML service, scheduled through the job runner.
//
// Routing uses the standard library's method+pattern mux; the API is small enough that a
// third-party router would add a dependency without adding clarity.
package httpapi

import (
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/farrelathalla/toothfairy/gateway/internal/auth"
	"github.com/farrelathalla/toothfairy/gateway/internal/config"
	"github.com/farrelathalla/toothfairy/gateway/internal/jobs"
	"github.com/farrelathalla/toothfairy/gateway/internal/middleware"
	"github.com/farrelathalla/toothfairy/gateway/internal/mlclient"
	"github.com/farrelathalla/toothfairy/gateway/internal/store"
)

type Server struct {
	cfg    config.Config
	store  *store.Store
	issuer *auth.Issuer
	ml     *mlclient.Client
	runner *jobs.Runner
	log    *slog.Logger
}

func NewServer(cfg config.Config, st *store.Store, issuer *auth.Issuer, ml *mlclient.Client,
	runner *jobs.Runner, log *slog.Logger) *Server {
	return &Server{cfg: cfg, store: st, issuer: issuer, ml: ml, runner: runner, log: log}
}

// Handler builds the fully wrapped handler.
//
// Middleware order is deliberate: Recover is outermost so it catches panics from every layer
// including the logger; RequestID precedes Logger so each line is correlatable; CORS runs
// before the auth check so a rejected preflight still carries the right headers; the rate
// limiter sits in front of the handlers so a flood is refused before it reaches the database.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /health", s.handleHealth)

	mux.HandleFunc("POST /auth/login", s.handleLogin)
	mux.HandleFunc("POST /auth/logout", s.handleLogout)
	mux.HandleFunc("GET /auth/me", s.requireAuth(s.handleMe))

	admin := store.RoleAdmin
	mux.HandleFunc("GET /accounts", s.requireRole(admin, s.handleListAccounts))
	mux.HandleFunc("POST /accounts", s.requireRole(admin, s.handleCreateAccount))
	mux.HandleFunc("PATCH /accounts/{id}", s.requireRole(admin, s.handleUpdateAccount))
	mux.HandleFunc("DELETE /accounts/{id}", s.requireRole(admin, s.handleDeleteAccount))

	doctor := store.RoleDoctor
	mux.HandleFunc("POST /cases", s.requireRole(doctor, s.handleCreateCase))
	mux.HandleFunc("GET /cases", s.requireAuth(s.handleListCases))
	mux.HandleFunc("GET /cases/{id}", s.requireAuth(s.handleGetCase))
	mux.HandleFunc("GET /cases/{id}/status", s.requireAuth(s.handleCaseStatus))
	mux.HandleFunc("POST /cases/{id}/images", s.requireRole(doctor, s.handleUploadImages))
	mux.HandleFunc("POST /cases/{id}/run", s.requireRole(doctor, s.handleRunCase))
	mux.HandleFunc("DELETE /cases/{id}", s.requireAuth(s.handleDeleteCase))

	mux.Handle("GET /media/", s.requireAuth(s.handleMedia))

	limiter := middleware.NewRateLimiter(s.cfg.RateLimitRPM, s.cfg.TrustedProxy)
	return middleware.Chain(mux,
		middleware.Recover(s.log),
		middleware.RequestID,
		middleware.Logger(s.log),
		middleware.SecurityHeaders,
		middleware.CORS(s.cfg.CORSOrigins),
		limiter.Middleware,
		middleware.MaxBody((s.cfg.MaxUploadMB+2)<<20),
	)
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	body := map[string]any{"ok": true, "service": "gateway", "env": s.cfg.Env}
	if health, err := s.ml.Health(r.Context()); err != nil {
		// The gateway itself is up; report the dependency truthfully rather than 500-ing,
		// so a load balancer keeps routing while an operator sees what is broken.
		body["ml"] = map[string]any{"ok": false, "error": err.Error()}
	} else {
		body["ml"] = health
	}
	writeJSON(w, http.StatusOK, body)
}

// handleMedia serves a patient's uploaded photos.
//
// Two properties matter. It is **authenticated** — patient photos are not public, so this is
// not a plain static mount. And the resolved path is checked to still live under the upload
// root, so no combination of encoded traversal segments can read outside it.
func (s *Server) handleMedia(w http.ResponseWriter, r *http.Request) {
	rel := strings.TrimPrefix(r.URL.Path, "/media/")
	if rel == "" {
		http.NotFound(w, r)
		return
	}

	root, err := filepath.Abs(s.cfg.UploadDir)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	full, err := filepath.Abs(filepath.Join(root, filepath.FromSlash(rel)))
	if err != nil || !strings.HasPrefix(full, root+string(os.PathSeparator)) {
		http.NotFound(w, r)
		return
	}

	// A doctor may only read media belonging to their own cases. The first path segment is
	// the case id, so ownership is one lookup.
	caseID, _, _ := strings.Cut(rel, "/")
	kase, err := s.store.GetCase(r.Context(), caseID)
	user := userFrom(r.Context())
	if err != nil || (kase.DoctorID != user.ID && user.Role != store.RoleAdmin) {
		http.NotFound(w, r)
		return
	}

	info, err := os.Stat(full)
	if err != nil || info.IsDir() {
		http.NotFound(w, r)
		return
	}
	http.ServeFile(w, r, full)
}
