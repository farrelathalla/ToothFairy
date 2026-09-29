package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/farrelathalla/toothfairy/gateway/internal/auth"
	"github.com/farrelathalla/toothfairy/gateway/internal/config"
	"github.com/farrelathalla/toothfairy/gateway/internal/jobs"
	"github.com/farrelathalla/toothfairy/gateway/internal/mlclient"
	"github.com/farrelathalla/toothfairy/gateway/internal/store"
)

// pngBytes is a real 1x1 PNG, so the content sniffer sees an actual image rather than a
// declared one — which is the point of sniffing.
var pngBytes = []byte{
	0x89, 'P', 'N', 'G', 0x0d, 0x0a, 0x1a, 0x0a,
	0, 0, 0, 0x0d, 'I', 'H', 'D', 'R',
	0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0, 0, 0, 0x1f, 0x15, 0xc4, 0x89,
	0, 0, 0, 0x0a, 'I', 'D', 'A', 'T', 0x78, 0x9c, 0x63, 0, 1, 0, 0, 5, 0, 1,
	0x0d, 0x0a, 0x2d, 0xb4, 0, 0, 0, 0, 'I', 'E', 'N', 'D', 0xae, 0x42, 0x60, 0x82,
}

type harness struct {
	t       *testing.T
	server  *Server
	handler http.Handler
	store   *store.Store
	mlStub  *httptest.Server
	cfg     config.Config

	// analyzeEvents is the NDJSON the stub ML service replies with.
	analyzeEvents string
	advisoryCode  int
}

func newHarness(t *testing.T) *harness {
	t.Helper()
	dir := t.TempDir()

	st, err := store.Open(filepath.Join(dir, "test.db"))
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { _ = st.Close() })

	h := &harness{
		t: t, store: st,
		analyzeEvents: `{"type":"progress","pct":50,"stage":"Deteksi"}` + "\n" +
			`{"type":"result","dataset_id":"case-x"}` + "\n",
		advisoryCode: http.StatusOK,
	}

	h.mlStub = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/health":
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "service": "ml"})
		case "/internal/analyze":
			w.Header().Set("Content-Type", "application/x-ndjson")
			_, _ = io.WriteString(w, h.analyzeEvents)
		case "/internal/advisory":
			if h.advisoryCode != http.StatusOK {
				w.WriteHeader(h.advisoryCode)
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"diagnosis_md": "# Diagnosis", "recommendation_md": "# Rekomendasi",
				"sanity_md": "# Konsistensi", "meta": map[string]any{"llm_enabled": false},
			})
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	t.Cleanup(h.mlStub.Close)

	h.cfg = config.Config{
		Env: "test", UploadDir: filepath.Join(dir, "uploads"),
		ResultsDir: filepath.Join(dir, "results"), MaxUploadMB: 2,
		CORSOrigins: []string{"http://localhost:3000"}, RateLimitRPM: 0,
	}
	if err := os.MkdirAll(h.cfg.UploadDir, 0o755); err != nil {
		t.Fatal(err)
	}

	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	ml := mlclient.New(h.mlStub.URL, "", 10*time.Second)
	runner := jobs.NewRunner(st, ml, h.cfg.UploadDir, 10*time.Second, log)
	runner.Start(1, 4)
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		runner.Shutdown(ctx)
	})

	h.server = NewServer(h.cfg, st, auth.NewIssuer("test-secret-at-least-32-bytes-long!!", time.Hour), ml, runner, log)
	h.handler = h.server.Handler()
	return h
}

// --- request helpers ---------------------------------------------------------

func (h *harness) do(method, path, token string, body any) *httptest.ResponseRecorder {
	h.t.Helper()
	var reader io.Reader
	if body != nil {
		blob, _ := json.Marshal(body)
		reader = bytes.NewReader(blob)
	}
	req := httptest.NewRequest(method, path, reader)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	rec := httptest.NewRecorder()
	h.handler.ServeHTTP(rec, req)
	return rec
}

func (h *harness) upload(caseID, token string, files map[string][]byte) *httptest.ResponseRecorder {
	h.t.Helper()
	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)
	for view, data := range files {
		part, _ := writer.CreateFormFile(view, view+".png")
		_, _ = part.Write(data)
	}
	_ = writer.Close()

	req := httptest.NewRequest(http.MethodPost, "/cases/"+caseID+"/images", &buf)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	h.handler.ServeHTTP(rec, req)
	return rec
}

func (h *harness) account(email string, role store.Role) (*store.User, string) {
	h.t.Helper()
	hash, err := auth.HashPassword("secret123")
	if err != nil {
		h.t.Fatal(err)
	}
	user, err := h.store.CreateUser(h.t.Context(), email, "Test "+string(role), role, hash)
	if err != nil {
		h.t.Fatal(err)
	}
	token, err := auth.NewIssuer("test-secret-at-least-32-bytes-long!!", time.Hour).
		Issue(user.ID, string(user.Role))
	if err != nil {
		h.t.Fatal(err)
	}
	return user, token
}

func decode[T any](t *testing.T, rec *httptest.ResponseRecorder) T {
	t.Helper()
	var out T
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatalf("decode %s: %v", rec.Body.String(), err)
	}
	return out
}

func validAnamnesa() map[string]string {
	return map[string]string{
		"lokasi": "Gigi depan atas", "quality": "Ngilu", "alasan_kuat": "Nyeri saat makan",
	}
}

func (h *harness) newCase(token string) string {
	h.t.Helper()
	rec := h.do(http.MethodPost, "/cases", token, map[string]any{
		"patient_name": "Anak A", "anamnesa": validAnamnesa(),
	})
	if rec.Code != http.StatusCreated {
		h.t.Fatalf("create case: %d %s", rec.Code, rec.Body.String())
	}
	return decode[store.Case](h.t, rec).ID
}

// --- health ------------------------------------------------------------------

func TestHealthReportsBothServices(t *testing.T) {
	h := newHarness(t)
	rec := h.do(http.MethodGet, "/health", "", nil)
	if rec.Code != http.StatusOK {
		t.Fatalf("got %d", rec.Code)
	}
	body := decode[map[string]any](t, rec)
	if body["ok"] != true {
		t.Errorf("gateway not ok: %v", body)
	}
	if ml, _ := body["ml"].(map[string]any); ml["ok"] != true {
		t.Errorf("ml health not reported: %v", body["ml"])
	}
}

func TestHealthStaysUpWhenTheMLServiceIsDown(t *testing.T) {
	h := newHarness(t)
	h.mlStub.Close()

	rec := h.do(http.MethodGet, "/health", "", nil)
	if rec.Code != http.StatusOK {
		t.Fatalf("gateway should stay healthy on its own, got %d", rec.Code)
	}
	ml, _ := decode[map[string]any](t, rec)["ml"].(map[string]any)
	if ml["ok"] != false {
		t.Errorf("expected the dependency reported as down, got %v", ml)
	}
}

// --- auth --------------------------------------------------------------------

func TestLoginReturnsATokenAndSetsAnHttpOnlyCookie(t *testing.T) {
	h := newHarness(t)
	h.account("doctor@x.io", store.RoleDoctor)

	rec := h.do(http.MethodPost, "/auth/login", "", map[string]string{
		"email": "doctor@x.io", "password": "secret123",
	})
	if rec.Code != http.StatusOK {
		t.Fatalf("login failed: %d %s", rec.Code, rec.Body.String())
	}
	body := decode[loginResponse](t, rec)
	if body.Token == "" || body.User == nil || body.User.Email != "doctor@x.io" {
		t.Fatalf("unexpected body: %+v", body)
	}
	if strings.Contains(rec.Body.String(), "password_hash") {
		t.Error("password hash leaked into the response")
	}

	cookie := rec.Result().Cookies()
	if len(cookie) == 0 || cookie[0].Name != sessionCookie || !cookie[0].HttpOnly {
		t.Errorf("expected an httpOnly session cookie, got %+v", cookie)
	}
}

func TestLoginIsCaseInsensitiveOnEmail(t *testing.T) {
	h := newHarness(t)
	h.account("doctor@x.io", store.RoleDoctor)

	rec := h.do(http.MethodPost, "/auth/login", "", map[string]string{
		"email": "  Doctor@X.IO ", "password": "secret123",
	})
	if rec.Code != http.StatusOK {
		t.Fatalf("got %d", rec.Code)
	}
}

func TestLoginDoesNotRevealWhetherAnAccountExists(t *testing.T) {
	h := newHarness(t)
	h.account("doctor@x.io", store.RoleDoctor)

	wrongPassword := h.do(http.MethodPost, "/auth/login", "", map[string]string{
		"email": "doctor@x.io", "password": "nope",
	})
	noSuchUser := h.do(http.MethodPost, "/auth/login", "", map[string]string{
		"email": "ghost@x.io", "password": "nope",
	})
	if wrongPassword.Code != noSuchUser.Code || wrongPassword.Body.String() != noSuchUser.Body.String() {
		t.Errorf("responses differ and leak account existence:\n  %d %s\n  %d %s",
			wrongPassword.Code, wrongPassword.Body.String(),
			noSuchUser.Code, noSuchUser.Body.String())
	}
}

func TestDeactivatedAccountLosesAccessImmediately(t *testing.T) {
	h := newHarness(t)
	user, token := h.account("doctor@x.io", store.RoleDoctor)

	if rec := h.do(http.MethodGet, "/auth/me", token, nil); rec.Code != http.StatusOK {
		t.Fatalf("expected access before deactivation, got %d", rec.Code)
	}
	inactive := false
	if _, err := h.store.UpdateUser(t.Context(), user.ID, store.UserUpdate{IsActive: &inactive}); err != nil {
		t.Fatal(err)
	}
	// The token is still cryptographically valid — access must stop anyway.
	if rec := h.do(http.MethodGet, "/auth/me", token, nil); rec.Code != http.StatusUnauthorized {
		t.Errorf("deactivated user still authorized: %d", rec.Code)
	}
}

func TestUnauthenticatedRequestsAreRejected(t *testing.T) {
	h := newHarness(t)
	for _, path := range []string{"/auth/me", "/cases", "/accounts"} {
		if rec := h.do(http.MethodGet, path, "", nil); rec.Code != http.StatusUnauthorized {
			t.Errorf("%s: expected 401, got %d", path, rec.Code)
		}
	}
}

func TestAGarbageOrForgedTokenIsRejected(t *testing.T) {
	h := newHarness(t)
	h.account("doctor@x.io", store.RoleDoctor)

	// Signed with a different secret — the signature check must catch it.
	forged, _ := auth.NewIssuer("some-other-secret-value-that-is-long", time.Hour).Issue(1, "admin")
	for _, token := range []string{"garbage", forged} {
		if rec := h.do(http.MethodGet, "/auth/me", token, nil); rec.Code != http.StatusUnauthorized {
			t.Errorf("token %q accepted: %d", token, rec.Code)
		}
	}
}

// --- RBAC --------------------------------------------------------------------

func TestDoctorsCannotReachAccountAdministration(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("doctor@x.io", store.RoleDoctor)

	if rec := h.do(http.MethodGet, "/accounts", token, nil); rec.Code != http.StatusForbidden {
		t.Errorf("expected 403, got %d", rec.Code)
	}
}

func TestAdminsCannotCreateCases(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("admin@x.io", store.RoleAdmin)

	rec := h.do(http.MethodPost, "/cases", token, map[string]any{"anamnesa": validAnamnesa()})
	if rec.Code != http.StatusForbidden {
		t.Errorf("expected 403, got %d", rec.Code)
	}
}

func TestLastActiveAdminCannotBeRemovedOrDemoted(t *testing.T) {
	h := newHarness(t)
	admin, token := h.account("admin@x.io", store.RoleAdmin)

	demote := h.do(http.MethodPatch, fmt.Sprintf("/accounts/%d", admin.ID), token,
		map[string]any{"role": "doctor"})
	if demote.Code != http.StatusConflict {
		t.Errorf("demoting the last admin returned %d", demote.Code)
	}

	other, _ := h.account("admin2@x.io", store.RoleAdmin)
	del := h.do(http.MethodDelete, fmt.Sprintf("/accounts/%d", other.ID), token, nil)
	if del.Code != http.StatusNoContent {
		t.Errorf("deleting a non-last admin returned %d %s", del.Code, del.Body.String())
	}
}

func TestAdminCannotDeleteThemselves(t *testing.T) {
	h := newHarness(t)
	admin, token := h.account("admin@x.io", store.RoleAdmin)
	h.account("admin2@x.io", store.RoleAdmin)

	rec := h.do(http.MethodDelete, fmt.Sprintf("/accounts/%d", admin.ID), token, nil)
	if rec.Code != http.StatusConflict {
		t.Errorf("expected 409, got %d", rec.Code)
	}
}

func TestAccountCreationValidatesItsInput(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("admin@x.io", store.RoleAdmin)

	cases := []struct {
		name string
		body map[string]any
	}{
		{"bad email", map[string]any{"email": "nope", "name": "X", "password": "secret123"}},
		{"empty name", map[string]any{"email": "a@b.io", "name": " ", "password": "secret123"}},
		{"short password", map[string]any{"email": "a@b.io", "name": "X", "password": "12"}},
		{"unknown role", map[string]any{"email": "a@b.io", "name": "X", "password": "secret123", "role": "root"}},
	}
	for _, tc := range cases {
		if rec := h.do(http.MethodPost, "/accounts", token, tc.body); rec.Code != http.StatusBadRequest {
			t.Errorf("%s: expected 400, got %d %s", tc.name, rec.Code, rec.Body.String())
		}
	}
}

func TestDuplicateEmailIsAConflict(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("admin@x.io", store.RoleAdmin)

	body := map[string]any{"email": "new@x.io", "name": "New", "password": "secret123"}
	if rec := h.do(http.MethodPost, "/accounts", token, body); rec.Code != http.StatusCreated {
		t.Fatalf("first create: %d %s", rec.Code, rec.Body.String())
	}
	if rec := h.do(http.MethodPost, "/accounts", token, body); rec.Code != http.StatusConflict {
		t.Errorf("expected 409, got %d", rec.Code)
	}
}

// --- cases -------------------------------------------------------------------

func TestCaseCreationRequiresTheCoreAnamnesaQuestions(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("doctor@x.io", store.RoleDoctor)

	rec := h.do(http.MethodPost, "/cases", token, map[string]any{
		"anamnesa": map[string]string{"lokasi": "Gigi depan atas"},
	})
	if rec.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d %s", rec.Code, rec.Body.String())
	}
}

func TestUnknownAnamnesaKeysAreDroppedNotStored(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("doctor@x.io", store.RoleDoctor)

	anamnesa := validAnamnesa()
	anamnesa["nomor_ktp"] = "3201234567890001"
	rec := h.do(http.MethodPost, "/cases", token, map[string]any{"anamnesa": anamnesa})
	if rec.Code != http.StatusCreated {
		t.Fatalf("create: %d %s", rec.Code, rec.Body.String())
	}
	if _, ok := decode[store.Case](t, rec).Anamnesa["nomor_ktp"]; ok {
		t.Error("an unexpected field was persisted onto the case")
	}
}

func TestDoctorsOnlySeeTheirOwnCases(t *testing.T) {
	h := newHarness(t)
	_, mine := h.account("a@x.io", store.RoleDoctor)
	_, theirs := h.account("b@x.io", store.RoleDoctor)

	caseID := h.newCase(mine)

	list := decode[[]store.Case](t, h.do(http.MethodGet, "/cases", theirs, nil))
	if len(list) != 0 {
		t.Errorf("another doctor's history leaked: %+v", list)
	}
	// Someone else's case reads as 404, not 403 — a 403 would confirm the id exists.
	if rec := h.do(http.MethodGet, "/cases/"+caseID, theirs, nil); rec.Code != http.StatusNotFound {
		t.Errorf("expected 404, got %d", rec.Code)
	}
}

func TestAdminsSeeEveryCase(t *testing.T) {
	h := newHarness(t)
	_, doctor := h.account("a@x.io", store.RoleDoctor)
	_, admin := h.account("admin@x.io", store.RoleAdmin)
	h.newCase(doctor)

	list := decode[[]store.Case](t, h.do(http.MethodGet, "/cases", admin, nil))
	if len(list) != 1 {
		t.Errorf("admin should see all cases, got %d", len(list))
	}
}

// --- uploads -----------------------------------------------------------------

func TestUploadStoresOneImagePerViewSlot(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("doctor@x.io", store.RoleDoctor)
	caseID := h.newCase(token)

	rec := h.upload(caseID, token, map[string][]byte{"up": pngBytes, "panoramic": pngBytes})
	if rec.Code != http.StatusOK {
		t.Fatalf("upload: %d %s", rec.Code, rec.Body.String())
	}
	kase := decode[store.Case](t, rec)
	if len(kase.Images) != 2 {
		t.Fatalf("expected 2 images, got %d", len(kase.Images))
	}
	if kase.Status != store.StatusUploaded {
		t.Errorf("expected status uploaded, got %s", kase.Status)
	}
	for _, img := range kase.Images {
		if !strings.HasPrefix(img.URL, "/media/"+caseID+"/") {
			t.Errorf("unexpected media url %q", img.URL)
		}
		if _, err := os.Stat(filepath.Join(h.cfg.UploadDir, filepath.FromSlash(img.Path))); err != nil {
			t.Errorf("file not written: %v", err)
		}
	}
}

func TestReuploadingAViewReplacesItRatherThanAccumulating(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("doctor@x.io", store.RoleDoctor)
	caseID := h.newCase(token)

	h.upload(caseID, token, map[string][]byte{"up": pngBytes})
	rec := h.upload(caseID, token, map[string][]byte{"up": pngBytes})
	if got := len(decode[store.Case](t, rec).Images); got != 1 {
		t.Errorf("expected the slot replaced, got %d images", got)
	}
}

func TestNonImageUploadsAreRejectedBySniffingNotByFilename(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("doctor@x.io", store.RoleDoctor)
	caseID := h.newCase(token)

	rec := h.upload(caseID, token, map[string][]byte{
		"up": []byte("#!/bin/sh\necho not an image\n"),
	})
	if rec.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d %s", rec.Code, rec.Body.String())
	}
}

func TestUploadWithNoRecognizedViewIsRejected(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("doctor@x.io", store.RoleDoctor)
	caseID := h.newCase(token)

	rec := h.upload(caseID, token, map[string][]byte{"selfie": pngBytes})
	if rec.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d", rec.Code)
	}
}

// --- media -------------------------------------------------------------------

func TestMediaRequiresAuthenticationAndOwnership(t *testing.T) {
	h := newHarness(t)
	_, mine := h.account("a@x.io", store.RoleDoctor)
	_, theirs := h.account("b@x.io", store.RoleDoctor)
	caseID := h.newCase(mine)
	h.upload(caseID, mine, map[string][]byte{"up": pngBytes})

	path := "/media/" + caseID + "/up.png"
	if rec := h.do(http.MethodGet, path, "", nil); rec.Code != http.StatusUnauthorized {
		t.Errorf("anonymous read allowed: %d", rec.Code)
	}
	if rec := h.do(http.MethodGet, path, theirs, nil); rec.Code != http.StatusNotFound {
		t.Errorf("another doctor read the photo: %d", rec.Code)
	}
	if rec := h.do(http.MethodGet, path, mine, nil); rec.Code != http.StatusOK {
		t.Errorf("owner could not read the photo: %d", rec.Code)
	}
}

func TestMediaAcceptsAQueryTokenBecauseImgTagsCannotSendHeaders(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("a@x.io", store.RoleDoctor)
	caseID := h.newCase(token)
	h.upload(caseID, token, map[string][]byte{"up": pngBytes})

	rec := h.do(http.MethodGet, "/media/"+caseID+"/up.png?token="+token, "", nil)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if cc := rec.Header().Get("Cache-Control"); !strings.Contains(cc, "no-store") {
		t.Errorf("patient media must not be cacheable, got %q", cc)
	}
}

func TestMediaPathTraversalIsRefused(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("a@x.io", store.RoleDoctor)
	secret := filepath.Join(filepath.Dir(h.cfg.UploadDir), "secret.txt")
	if err := os.WriteFile(secret, []byte("classified"), 0o600); err != nil {
		t.Fatal(err)
	}

	for _, path := range []string{
		"/media/../secret.txt",
		"/media/..%2fsecret.txt",
		"/media/foo/../../secret.txt",
	} {
		rec := h.do(http.MethodGet, path, token, nil)
		if rec.Code == http.StatusOK && strings.Contains(rec.Body.String(), "classified") {
			t.Errorf("%s escaped the upload root", path)
		}
	}
}

// --- running a case ----------------------------------------------------------

func TestRunRequiresAtLeastOneImage(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("doctor@x.io", store.RoleDoctor)
	caseID := h.newCase(token)

	rec := h.do(http.MethodPost, "/cases/"+caseID+"/run", token, nil)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d %s", rec.Code, rec.Body.String())
	}
}

func TestRunDrivesTheCaseToDoneAndStoresTheAdvisory(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("doctor@x.io", store.RoleDoctor)
	caseID := h.newCase(token)
	h.upload(caseID, token, map[string][]byte{"up": pngBytes})
	h.analyzeEvents = `{"type":"progress","pct":40,"stage":"Deteksi"}` + "\n" +
		`{"type":"result","dataset_id":"` + caseID + `"}` + "\n"

	if rec := h.do(http.MethodPost, "/cases/"+caseID+"/run", token, nil); rec.Code != http.StatusAccepted {
		t.Fatalf("run: %d %s", rec.Code, rec.Body.String())
	}

	final := h.waitForStatus(caseID, token, store.StatusDone)
	if final.Progress != 100 {
		t.Errorf("expected progress 100, got %d", final.Progress)
	}
	kase := decode[store.Case](t, h.do(http.MethodGet, "/cases/"+caseID, token, nil))
	if kase.DiagnosisMD == nil || *kase.DiagnosisMD != "# Diagnosis" {
		t.Errorf("diagnosis not stored: %+v", kase.DiagnosisMD)
	}
	if kase.RecommendationMD == nil || *kase.RecommendationMD != "# Rekomendasi" {
		t.Errorf("recommendation not stored: %+v", kase.RecommendationMD)
	}
}

func TestAnalysisFailureIsRecordedOnTheCase(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("doctor@x.io", store.RoleDoctor)
	caseID := h.newCase(token)
	h.upload(caseID, token, map[string][]byte{"up": pngBytes})
	h.analyzeEvents = `{"type":"error","message":"bobot model tidak ditemukan"}` + "\n"

	h.do(http.MethodPost, "/cases/"+caseID+"/run", token, nil)
	final := h.waitForStatus(caseID, token, store.StatusFailed)
	if final.Error == nil || !strings.Contains(*final.Error, "bobot model") {
		t.Errorf("failure reason not surfaced: %+v", final.Error)
	}
}

func TestAdvisoryFailureStillCompletesTheCase(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("doctor@x.io", store.RoleDoctor)
	caseID := h.newCase(token)
	h.upload(caseID, token, map[string][]byte{"up": pngBytes})
	h.analyzeEvents = `{"type":"result","dataset_id":"` + caseID + `"}` + "\n"
	h.advisoryCode = http.StatusInternalServerError

	h.do(http.MethodPost, "/cases/"+caseID+"/run", token, nil)
	// The detection and 3D reconstruction succeeded; losing the advisory text must not
	// throw that away.
	final := h.waitForStatus(caseID, token, store.StatusDone)
	if final.DatasetID == nil || *final.DatasetID != caseID {
		t.Errorf("dataset id lost: %+v", final.DatasetID)
	}
}

func (h *harness) waitForStatus(caseID, token string, want store.CaseStatus) caseStatus {
	h.t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	var last caseStatus
	for time.Now().Before(deadline) {
		last = decode[caseStatus](h.t, h.do(http.MethodGet, "/cases/"+caseID+"/status", token, nil))
		if last.Status == want {
			return last
		}
		time.Sleep(20 * time.Millisecond)
	}
	h.t.Fatalf("case never reached %s (last: %+v)", want, last)
	return last
}

// --- deletion ----------------------------------------------------------------

func TestDeletingACaseAlsoErasesItsUploadedPhotos(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("doctor@x.io", store.RoleDoctor)
	caseID := h.newCase(token)
	h.upload(caseID, token, map[string][]byte{"up": pngBytes})

	if rec := h.do(http.MethodDelete, "/cases/"+caseID, token, nil); rec.Code != http.StatusNoContent {
		t.Fatalf("delete: %d %s", rec.Code, rec.Body.String())
	}
	if _, err := os.Stat(filepath.Join(h.cfg.UploadDir, caseID)); !os.IsNotExist(err) {
		t.Error("patient photos survived the deletion")
	}
	if rec := h.do(http.MethodGet, "/cases/"+caseID, token, nil); rec.Code != http.StatusNotFound {
		t.Errorf("case still readable: %d", rec.Code)
	}
}

// --- transport-level guards --------------------------------------------------

func TestSecurityHeadersArePresent(t *testing.T) {
	h := newHarness(t)
	rec := h.do(http.MethodGet, "/health", "", nil)
	for header, want := range map[string]string{
		"X-Content-Type-Options": "nosniff",
		"X-Frame-Options":        "DENY",
		"Referrer-Policy":        "no-referrer",
	} {
		if got := rec.Header().Get(header); got != want {
			t.Errorf("%s = %q, want %q", header, got, want)
		}
	}
}

func TestCORSReflectsOnlyAllowedOrigins(t *testing.T) {
	h := newHarness(t)

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	req.Header.Set("Origin", "http://localhost:3000")
	rec := httptest.NewRecorder()
	h.handler.ServeHTTP(rec, req)
	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != "http://localhost:3000" {
		t.Errorf("allowed origin not reflected: %q", got)
	}

	req = httptest.NewRequest(http.MethodGet, "/health", nil)
	req.Header.Set("Origin", "https://evil.example")
	rec = httptest.NewRecorder()
	h.handler.ServeHTTP(rec, req)
	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Errorf("unknown origin was allowed: %q", got)
	}
}

func TestMalformedJSONAndUnknownFieldsAreRejected(t *testing.T) {
	h := newHarness(t)
	_, token := h.account("doctor@x.io", store.RoleDoctor)

	req := httptest.NewRequest(http.MethodPost, "/cases", strings.NewReader("{not json"))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	h.handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("malformed body: expected 400, got %d", rec.Code)
	}

	unknown := h.do(http.MethodPost, "/cases", token, map[string]any{
		"anamnesa": validAnamnesa(), "is_admin": true,
	})
	if unknown.Code != http.StatusBadRequest {
		t.Errorf("unknown field: expected 400, got %d", unknown.Code)
	}
}
