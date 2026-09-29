package httpapi

import (
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"

	"github.com/farrelathalla/toothfairy/gateway/internal/jobs"
	"github.com/farrelathalla/toothfairy/gateway/internal/store"
)

// requiredAnamnesa are the two questions a case is clinically useless without: what the
// complaint is and why the patient came. The rest of the questionnaire is optional free text.
var requiredAnamnesa = []string{"lokasi", "quality", "alasan_kuat"}

// anamnesaFields is the accepted key set. Anything else is dropped rather than stored — the
// anamnesa is a JSON blob, and an open blob is how unexpected personal data ends up in a
// database nobody remembers to purge.
var anamnesaFields = []string{
	"lokasi", "quality", "severity", "chronology", "setting",
	"aggravating_alleviating", "associated", "pernah_ke_drg_lain", "obat_digunakan",
	"tindakan_sebelumnya", "penyakit_sistemik", "pernah_menunda", "alasan_kuat",
}

const (
	maxAnamnesaFieldLen = 2000
	maxPatientNameLen   = 255
)

// allowedImageTypes maps a sniffed content type to the extension we store it under. The
// stored name never comes from the client, so a crafted filename cannot traverse the
// upload directory or land as an executable extension.
var allowedImageTypes = map[string]string{
	"image/jpeg": ".jpg",
	"image/png":  ".png",
	"image/webp": ".webp",
	"image/bmp":  ".bmp",
}

type caseCreate struct {
	PatientName *string           `json:"patient_name"`
	Anamnesa    map[string]string `json:"anamnesa"`
}

type runResponse struct {
	Status  store.CaseStatus `json:"status"`
	CaseID  string           `json:"case_id"`
	Message string           `json:"message,omitempty"`
}

type caseStatus struct {
	Status    store.CaseStatus `json:"status"`
	Progress  int              `json:"progress"`
	Stage     *string          `json:"stage"`
	Error     *string          `json:"error"`
	DatasetID *string          `json:"dataset_id"`
}

// withMediaURLs fills each image's public URL. Stored paths stay relative so the media root
// can move between environments without a migration.
func (s *Server) withMediaURLs(c *store.Case) *store.Case {
	for i := range c.Images {
		c.Images[i].URL = "/media/" + c.Images[i].Path
	}
	return c
}

func sanitizeAnamnesa(in map[string]string) (map[string]any, error) {
	out := make(map[string]any, len(anamnesaFields))
	for _, field := range anamnesaFields {
		value := trim(in[field])
		if len(value) > maxAnamnesaFieldLen {
			return nil, fmt.Errorf("jawaban '%s' terlalu panjang", field)
		}
		out[field] = value
	}
	for _, field := range requiredAnamnesa {
		if out[field] == "" {
			return nil, fmt.Errorf("pertanyaan '%s' wajib diisi", field)
		}
	}
	return out, nil
}

func (s *Server) handleCreateCase(w http.ResponseWriter, r *http.Request) {
	var req caseCreate
	if err := decodeJSON(w, r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "Format permintaan tidak valid")
		return
	}
	anamnesa, err := sanitizeAnamnesa(req.Anamnesa)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	var name *string
	if req.PatientName != nil {
		trimmed := trim(*req.PatientName)
		if len(trimmed) > maxPatientNameLen {
			writeError(w, http.StatusBadRequest, "Nama pasien terlalu panjang")
			return
		}
		if trimmed != "" {
			name = &trimmed
		}
	}

	kase, err := s.store.CreateCase(r.Context(), userFrom(r.Context()).ID, name, anamnesa)
	if err != nil {
		s.log.Error("create case", "err", err)
		writeError(w, http.StatusInternalServerError, "Gagal membuat kasus")
		return
	}
	writeJSON(w, http.StatusCreated, s.withMediaURLs(kase))
}

func (s *Server) handleListCases(w http.ResponseWriter, r *http.Request) {
	user := userFrom(r.Context())
	scope := user.ID
	if user.Role == store.RoleAdmin {
		scope = 0 // admins see every case
	}
	cases, err := s.store.ListCases(r.Context(), scope)
	if err != nil {
		s.log.Error("list cases", "err", err)
		writeError(w, http.StatusInternalServerError, "Gagal memuat riwayat")
		return
	}
	writeJSON(w, http.StatusOK, cases)
}

// loadOwned fetches a case the caller is allowed to see. A case owned by someone else is
// reported as **not found**, not forbidden — otherwise the endpoint confirms which case ids
// exist for other doctors.
func (s *Server) loadOwned(w http.ResponseWriter, r *http.Request) *store.Case {
	kase, err := s.store.GetCase(r.Context(), r.PathValue("id"))
	if err != nil {
		if !errors.Is(err, store.ErrNotFound) {
			s.log.Error("load case", "err", err)
			writeError(w, http.StatusInternalServerError, "Gagal memuat kasus")
			return nil
		}
		writeError(w, http.StatusNotFound, "Kasus tidak ditemukan")
		return nil
	}
	user := userFrom(r.Context())
	if kase.DoctorID != user.ID && user.Role != store.RoleAdmin {
		writeError(w, http.StatusNotFound, "Kasus tidak ditemukan")
		return nil
	}
	return kase
}

func (s *Server) handleGetCase(w http.ResponseWriter, r *http.Request) {
	if kase := s.loadOwned(w, r); kase != nil {
		writeJSON(w, http.StatusOK, s.withMediaURLs(kase))
	}
}

func (s *Server) handleCaseStatus(w http.ResponseWriter, r *http.Request) {
	kase := s.loadOwned(w, r)
	if kase == nil {
		return
	}
	writeJSON(w, http.StatusOK, caseStatus{
		Status: kase.Status, Progress: kase.Progress, Stage: kase.Stage,
		Error: kase.Error, DatasetID: kase.DatasetID,
	})
}

func (s *Server) handleUploadImages(w http.ResponseWriter, r *http.Request) {
	kase := s.loadOwned(w, r)
	if kase == nil {
		return
	}
	if kase.Status == store.StatusRunning || kase.Status == store.StatusQueued {
		writeError(w, http.StatusConflict, "Analisis sedang berjalan untuk kasus ini")
		return
	}

	// Parse into memory up to one file's worth; the rest spills to a temp file, and
	// MaxBody has already capped the whole request.
	if err := r.ParseMultipartForm(s.cfg.MaxUploadMB << 20); err != nil {
		writeError(w, http.StatusBadRequest, "Gagal membaca unggahan (mungkin melebihi batas ukuran)")
		return
	}
	defer func() { _ = r.MultipartForm.RemoveAll() }()

	saved := 0
	for _, viewKey := range store.ViewKeys {
		files := r.MultipartForm.File[viewKey]
		if len(files) == 0 {
			continue
		}
		relPath, err := s.saveUpload(kase.ID, viewKey, files[0])
		if err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}
		if err := s.store.UpsertImage(r.Context(), kase.ID, viewKey, relPath); err != nil {
			s.log.Error("record upload", "err", err)
			writeError(w, http.StatusInternalServerError, "Gagal menyimpan gambar")
			return
		}
		saved++
	}

	if saved == 0 {
		writeError(w, http.StatusBadRequest, "Tidak ada gambar diunggah")
		return
	}

	updated, err := s.store.GetCase(r.Context(), kase.ID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Gagal memuat kasus")
		return
	}
	writeJSON(w, http.StatusOK, s.withMediaURLs(updated))
}

// saveUpload writes one view's photo and returns its path relative to the upload root.
//
// The content type is **sniffed from the bytes**, not taken from the multipart header: a
// client-declared type is a suggestion, and accepting it would let anything be stored under
// an image extension.
func (s *Server) saveUpload(caseID, viewKey string, header *multipart.FileHeader) (string, error) {
	if header.Size == 0 {
		return "", fmt.Errorf("berkas '%s' kosong", viewKey)
	}
	if header.Size > s.cfg.MaxUploadMB<<20 {
		return "", fmt.Errorf("berkas '%s' melebihi %d MB", viewKey, s.cfg.MaxUploadMB)
	}

	src, err := header.Open()
	if err != nil {
		return "", fmt.Errorf("gagal membaca berkas '%s'", viewKey)
	}
	defer src.Close()

	sniff := make([]byte, 512)
	n, _ := io.ReadFull(src, sniff)
	ext, ok := allowedImageTypes[strings.Split(http.DetectContentType(sniff[:n]), ";")[0]]
	if !ok {
		return "", fmt.Errorf("berkas '%s' bukan gambar JPEG/PNG/WebP/BMP", viewKey)
	}
	if _, err := src.Seek(0, io.SeekStart); err != nil {
		return "", fmt.Errorf("gagal membaca berkas '%s'", viewKey)
	}

	dir := filepath.Join(s.cfg.UploadDir, caseID)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", fmt.Errorf("gagal menyiapkan penyimpanan")
	}

	// The stored name is derived entirely from the (validated) view key and sniffed type.
	name := viewKey + ext
	dst, err := os.Create(filepath.Join(dir, name))
	if err != nil {
		return "", fmt.Errorf("gagal menyimpan berkas '%s'", viewKey)
	}
	defer dst.Close()

	if _, err := io.Copy(dst, io.LimitReader(src, s.cfg.MaxUploadMB<<20)); err != nil {
		return "", fmt.Errorf("gagal menyimpan berkas '%s'", viewKey)
	}
	// Forward slashes: this becomes part of a URL as well as a filesystem path.
	return path.Join(caseID, name), nil
}

func (s *Server) handleRunCase(w http.ResponseWriter, r *http.Request) {
	kase := s.loadOwned(w, r)
	if kase == nil {
		return
	}
	if len(kase.Images) == 0 {
		writeError(w, http.StatusBadRequest,
			"Unggah minimal satu gambar sebelum menjalankan analisis")
		return
	}
	if kase.Status == store.StatusQueued || kase.Status == store.StatusRunning {
		writeJSON(w, http.StatusAccepted, runResponse{
			Status: kase.Status, CaseID: kase.ID, Message: "Analisis sudah berjalan",
		})
		return
	}

	if err := s.runner.Enqueue(r.Context(), kase.ID); err != nil {
		if errors.Is(err, jobs.ErrQueueFull) {
			w.Header().Set("Retry-After", "30")
			writeError(w, http.StatusServiceUnavailable,
				"Antrean analisis sedang penuh, coba lagi sebentar lagi")
			return
		}
		s.log.Error("enqueue case", "err", err)
		writeError(w, http.StatusInternalServerError, "Gagal menjadwalkan analisis")
		return
	}
	writeJSON(w, http.StatusAccepted, runResponse{Status: store.StatusQueued, CaseID: kase.ID})
}

func (s *Server) handleDeleteCase(w http.ResponseWriter, r *http.Request) {
	kase := s.loadOwned(w, r)
	if kase == nil {
		return
	}
	if kase.Status == store.StatusRunning || kase.Status == store.StatusQueued {
		writeError(w, http.StatusConflict, "Tidak dapat menghapus kasus yang sedang dianalisis")
		return
	}

	if err := s.store.DeleteCase(r.Context(), kase.ID); err != nil {
		s.log.Error("delete case", "err", err)
		writeError(w, http.StatusInternalServerError, "Gagal menghapus kasus")
		return
	}

	// Erase the patient's images and derived results too. A "delete" that leaves the photos
	// on disk is not a deletion, and this is the endpoint a data-erasure request lands on.
	if err := os.RemoveAll(filepath.Join(s.cfg.UploadDir, kase.ID)); err != nil {
		s.log.Warn("could not remove uploads", "case_id", kase.ID, "err", err)
	}
	if kase.DatasetID != nil && strings.HasPrefix(*kase.DatasetID, "case-") {
		if err := os.RemoveAll(filepath.Join(s.cfg.ResultsDir, *kase.DatasetID)); err != nil {
			s.log.Warn("could not remove results", "case_id", kase.ID, "err", err)
		}
	}
	w.WriteHeader(http.StatusNoContent)
}
