package httpapi

import (
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/farrelathalla/toothfairy/gateway/internal/auth"
	"github.com/farrelathalla/toothfairy/gateway/internal/store"
)

type accountCreate struct {
	Email    string     `json:"email"`
	Name     string     `json:"name"`
	Role     store.Role `json:"role"`
	Password string     `json:"password"`
}

type accountUpdate struct {
	Name     *string     `json:"name"`
	Role     *store.Role `json:"role"`
	IsActive *bool       `json:"is_active"`
	Password *string     `json:"password"`
}

// looksLikeEmail is a deliberately permissive shape check. Deep validation of an address is
// a fool's errand; what matters is that it is non-empty, has one @, and has a dotted domain.
func looksLikeEmail(s string) bool {
	local, domain, ok := strings.Cut(strings.TrimSpace(s), "@")
	return ok && local != "" && strings.Contains(domain, ".") && !strings.Contains(domain, "@")
}

func (s *Server) handleListAccounts(w http.ResponseWriter, r *http.Request) {
	users, err := s.store.ListUsers(r.Context())
	if err != nil {
		s.log.Error("list accounts", "err", err)
		writeError(w, http.StatusInternalServerError, "Gagal memuat daftar akun")
		return
	}
	writeJSON(w, http.StatusOK, users)
}

func (s *Server) handleCreateAccount(w http.ResponseWriter, r *http.Request) {
	var req accountCreate
	if err := decodeJSON(w, r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "Format permintaan tidak valid")
		return
	}
	if !looksLikeEmail(req.Email) {
		writeError(w, http.StatusBadRequest, "Alamat email tidak valid")
		return
	}
	if trim(req.Name) == "" {
		writeError(w, http.StatusBadRequest, "Nama wajib diisi")
		return
	}
	if req.Role == "" {
		req.Role = store.RoleDoctor
	}
	if !req.Role.Valid() {
		writeError(w, http.StatusBadRequest, "Peran tidak dikenal")
		return
	}

	hash, err := auth.HashPassword(req.Password)
	if err != nil {
		writeError(w, http.StatusBadRequest, "Kata sandi minimal 6 karakter")
		return
	}

	user, err := s.store.CreateUser(r.Context(), req.Email, trim(req.Name), req.Role, hash)
	if err != nil {
		if errors.Is(err, store.ErrEmailTaken) {
			writeError(w, http.StatusConflict, "Email sudah terdaftar")
			return
		}
		s.log.Error("create account", "err", err)
		writeError(w, http.StatusInternalServerError, "Gagal membuat akun")
		return
	}
	writeJSON(w, http.StatusCreated, user)
}

func (s *Server) handleUpdateAccount(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		writeError(w, http.StatusBadRequest, "ID akun tidak valid")
		return
	}
	var req accountUpdate
	if err := decodeJSON(w, r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "Format permintaan tidak valid")
		return
	}

	up := store.UserUpdate{IsActive: req.IsActive}
	if req.Name != nil {
		name := trim(*req.Name)
		if name == "" {
			writeError(w, http.StatusBadRequest, "Nama tidak boleh kosong")
			return
		}
		up.Name = &name
	}
	if req.Role != nil {
		if !req.Role.Valid() {
			writeError(w, http.StatusBadRequest, "Peran tidak dikenal")
			return
		}
		up.Role = req.Role
	}
	if req.Password != nil {
		hash, err := auth.HashPassword(*req.Password)
		if err != nil {
			writeError(w, http.StatusBadRequest, "Kata sandi minimal 6 karakter")
			return
		}
		up.PasswordHash = &hash
	}

	// Locking every admin out of the system is not a recoverable mistake, so demoting or
	// deactivating the last active admin is refused rather than confirmed.
	demoting := (up.Role != nil && *up.Role != store.RoleAdmin) ||
		(up.IsActive != nil && !*up.IsActive)
	if demoting {
		if blocked, err := s.wouldOrphanAdmins(r, id); err != nil {
			writeError(w, http.StatusInternalServerError, "Gagal memeriksa akun admin")
			return
		} else if blocked {
			writeError(w, http.StatusConflict, "Tidak dapat menonaktifkan admin terakhir")
			return
		}
	}

	user, err := s.store.UpdateUser(r.Context(), id, up)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeError(w, http.StatusNotFound, "Akun tidak ditemukan")
			return
		}
		s.log.Error("update account", "err", err)
		writeError(w, http.StatusInternalServerError, "Gagal memperbarui akun")
		return
	}
	writeJSON(w, http.StatusOK, user)
}

func (s *Server) handleDeleteAccount(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		writeError(w, http.StatusBadRequest, "ID akun tidak valid")
		return
	}
	if userFrom(r.Context()).ID == id {
		writeError(w, http.StatusConflict, "Tidak dapat menghapus akun Anda sendiri")
		return
	}
	if blocked, err := s.wouldOrphanAdmins(r, id); err != nil {
		writeError(w, http.StatusInternalServerError, "Gagal memeriksa akun admin")
		return
	} else if blocked {
		writeError(w, http.StatusConflict, "Tidak dapat menghapus admin terakhir")
		return
	}

	if err := s.store.DeleteUser(r.Context(), id); err != nil {
		if errors.Is(err, store.ErrNotFound) {
			writeError(w, http.StatusNotFound, "Akun tidak ditemukan")
			return
		}
		s.log.Error("delete account", "err", err)
		writeError(w, http.StatusInternalServerError, "Gagal menghapus akun")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// wouldOrphanAdmins reports whether removing/demoting `id` leaves the system with no admin.
func (s *Server) wouldOrphanAdmins(r *http.Request, id int64) (bool, error) {
	target, err := s.store.GetUser(r.Context(), id)
	if err != nil {
		if errors.Is(err, store.ErrNotFound) {
			return false, nil // the not-found path reports itself
		}
		return false, err
	}
	if target.Role != store.RoleAdmin || !target.IsActive {
		return false, nil
	}
	admins, err := s.store.CountAdmins(r.Context())
	if err != nil {
		return false, err
	}
	return admins <= 1, nil
}
