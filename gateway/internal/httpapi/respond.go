package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strings"
)

// errorBody uses `detail` because that is what the web client reads (`data.detail`).
type errorBody struct {
	Detail string `json:"detail"`
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	if body == nil {
		return
	}
	if err := json.NewEncoder(w).Encode(body); err != nil {
		slog.Error("write response", "err", err)
	}
}

// writeError sends a client-safe message. Internal detail belongs in the log, not the body:
// a 500 that echoes a database error hands an attacker a map of the system.
func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, errorBody{Detail: message})
}

// decodeJSON reads a bounded JSON body and rejects unknown fields, so a typo in a client
// payload surfaces as a 400 rather than as a silently ignored setting.
func decodeJSON(w http.ResponseWriter, r *http.Request, dst any) error {
	dec := json.NewDecoder(io.LimitReader(r.Body, 1<<20))
	dec.DisallowUnknownFields()
	if err := dec.Decode(dst); err != nil {
		return err
	}
	// Exactly one JSON value, so a trailing document cannot smuggle anything past validation.
	if err := dec.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("body must contain a single JSON object")
	}
	return nil
}

func trim(s string) string { return strings.TrimSpace(s) }
