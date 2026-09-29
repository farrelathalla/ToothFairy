package httpapi

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/farrelathalla/toothfairy/gateway/internal/auth"
	"github.com/farrelathalla/toothfairy/gateway/internal/store"
)

type ctxKey string

const userKey ctxKey = "user"

// sessionCookie is set alongside the bearer token. The cookie is httpOnly so page scripts
// cannot read it; the token is also returned in the body because a SameSite=Lax cookie is
// not sent on the cross-origin dev fetch (`:3000` → `:8080`). Either credential is accepted.
const sessionCookie = "tf_session"

type loginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

type loginResponse struct {
	Token string      `json:"token"`
	User  *store.User `json:"user"`
}

func userFrom(ctx context.Context) *store.User {
	u, _ := ctx.Value(userKey).(*store.User)
	return u
}

// bearerToken pulls the credential from the Authorization header, falling back to the cookie.
func bearerToken(r *http.Request) string {
	header := r.Header.Get("Authorization")
	if after, ok := strings.CutPrefix(header, "Bearer "); ok {
		if token := trim(after); token != "" {
			return token
		}
	}
	if c, err := r.Cookie(sessionCookie); err == nil {
		return c.Value
	}
	return ""
}

// mediaToken additionally accepts `?token=`.
//
// Patient photos are rendered by `<img>`, which cannot set an Authorization header, and the
// session cookie is SameSite=Lax so the browser withholds it on a cross-origin subresource
// request. Leaving /media unauthenticated instead would publish patient photos to anyone who
// guessed a path, so the query parameter is the lesser evil — and its usual downsides are
// closed off deliberately: the access log records the path without the query string, the
// responses are `no-store`, and `Referrer-Policy: no-referrer` stops the URL leaking onward.
func mediaToken(r *http.Request) string {
	if token := bearerToken(r); token != "" {
		return token
	}
	return trim(r.URL.Query().Get("token"))
}

// authenticate resolves the caller, or nil. It never distinguishes "bad token" from "no
// token" to the client.
func (s *Server) authenticate(r *http.Request) *store.User {
	token := bearerToken(r)
	if token == "" && strings.HasPrefix(r.URL.Path, "/media/") {
		token = mediaToken(r)
	}
	if token == "" {
		return nil
	}
	userID, _, err := s.issuer.Verify(token)
	if err != nil {
		return nil
	}
	user, err := s.store.GetUser(r.Context(), userID)
	if err != nil || !user.IsActive {
		// A deactivated account must lose access immediately, even while its token is still
		// cryptographically valid — hence the lookup on every request.
		return nil
	}
	return user
}

// requireAuth gates a handler on any authenticated user.
func (s *Server) requireAuth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		user := s.authenticate(r)
		if user == nil {
			writeError(w, http.StatusUnauthorized, "Sesi tidak valid, silakan masuk kembali")
			return
		}
		next(w, r.WithContext(context.WithValue(r.Context(), userKey, user)))
	}
}

// requireRole gates a handler on a specific role.
func (s *Server) requireRole(role store.Role, next http.HandlerFunc) http.HandlerFunc {
	return s.requireAuth(func(w http.ResponseWriter, r *http.Request) {
		if userFrom(r.Context()).Role != role {
			writeError(w, http.StatusForbidden, "Anda tidak memiliki akses ke sumber daya ini")
			return
		}
		next(w, r)
	})
}

func (s *Server) handleLogin(w http.ResponseWriter, r *http.Request) {
	var req loginRequest
	if err := decodeJSON(w, r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "Format permintaan tidak valid")
		return
	}

	user, err := s.store.GetUserByEmail(r.Context(), req.Email)
	// One message and one code for every failure mode — a distinct "unknown email" reply
	// would turn this endpoint into an account-enumeration oracle.
	const denied = "Email atau kata sandi salah"
	if err != nil {
		if !errors.Is(err, store.ErrNotFound) {
			s.log.Error("login lookup failed", "err", err)
			writeError(w, http.StatusInternalServerError, "Terjadi kesalahan internal")
			return
		}
		// Still spend the hashing time so a missing account is not measurably faster.
		auth.CheckPassword("$2a$10$invalidinvalidinvalidinvalidinvalidinvalidinvalidinvalidinv", req.Password)
		writeError(w, http.StatusUnauthorized, denied)
		return
	}
	if !user.IsActive || !auth.CheckPassword(user.PasswordHash, req.Password) {
		writeError(w, http.StatusUnauthorized, denied)
		return
	}

	token, err := s.issuer.Issue(user.ID, string(user.Role))
	if err != nil {
		s.log.Error("token issue failed", "err", err)
		writeError(w, http.StatusInternalServerError, "Terjadi kesalahan internal")
		return
	}

	http.SetCookie(w, &http.Cookie{
		Name:     sessionCookie,
		Value:    token,
		Path:     "/",
		HttpOnly: true,
		Secure:   s.cfg.IsProduction(),
		SameSite: http.SameSiteLaxMode,
		Expires:  time.Now().Add(s.issuer.TTL()),
	})
	writeJSON(w, http.StatusOK, loginResponse{Token: token, User: user})
}

func (s *Server) handleLogout(w http.ResponseWriter, r *http.Request) {
	http.SetCookie(w, &http.Cookie{
		Name: sessionCookie, Value: "", Path: "/", HttpOnly: true,
		Secure: s.cfg.IsProduction(), SameSite: http.SameSiteLaxMode, MaxAge: -1,
	})
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func (s *Server) handleMe(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, userFrom(r.Context()))
}
