package store

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"time"
)

type CaseStatus string

const (
	StatusDraft    CaseStatus = "draft"    // created, no images yet
	StatusUploaded CaseStatus = "uploaded" // at least one image uploaded
	StatusQueued   CaseStatus = "queued"   // analysis scheduled
	StatusRunning  CaseStatus = "running"  // analysis in progress
	StatusDone     CaseStatus = "done"     // results ready
	StatusFailed   CaseStatus = "failed"   // analysis errored
)

// ViewKeys is the canonical capture set, in display order. It must stay in step with
// `ml/app/views.py` — the ML service rejects anything else.
var ViewKeys = []string{"front", "side_left", "side_right", "up", "bottom", "panoramic"}

func ValidViewKey(k string) bool {
	for _, v := range ViewKeys {
		if v == k {
			return true
		}
	}
	return false
}

type CaseImage struct {
	ViewKey string `json:"view_key"`
	Path    string `json:"path"`
	URL     string `json:"url"`
}

type Case struct {
	ID               string         `json:"id"`
	DoctorID         int64          `json:"doctor_id"`
	PatientName      *string        `json:"patient_name"`
	Anamnesa         map[string]any `json:"anamnesa"`
	Status           CaseStatus     `json:"status"`
	Progress         int            `json:"progress"`
	Stage            *string        `json:"stage"`
	DatasetID        *string        `json:"dataset_id"`
	Error            *string        `json:"error"`
	DiagnosisMD      *string        `json:"diagnosis_md"`
	RecommendationMD *string        `json:"recommendation_md"`
	SanityMD         *string        `json:"sanity_md"`
	CreatedAt        time.Time      `json:"created_at"`
	UpdatedAt        time.Time      `json:"updated_at"`
	Images           []CaseImage    `json:"images"`
}

// NewCaseID is time-ordered so a directory listing of results/ reads chronologically, with a
// random tail so ids stay unguessable in a URL.
func NewCaseID() string {
	buf := make([]byte, 3)
	_, _ = rand.Read(buf)
	return fmt.Sprintf("case-%s-%s", time.Now().UTC().Format("20060102-150405"), hex.EncodeToString(buf))
}

const caseColumns = `id, doctor_id, patient_name, anamnesa, status, progress, stage,
	dataset_id, error, diagnosis_md, recommendation_md, sanity_md, created_at, updated_at`

func scanCase(row interface{ Scan(...any) error }) (*Case, error) {
	var c Case
	var anamnesa, created, updated string
	err := row.Scan(&c.ID, &c.DoctorID, &c.PatientName, &anamnesa, &c.Status, &c.Progress,
		&c.Stage, &c.DatasetID, &c.Error, &c.DiagnosisMD, &c.RecommendationMD, &c.SanityMD,
		&created, &updated)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	c.Anamnesa = map[string]any{}
	_ = json.Unmarshal([]byte(anamnesa), &c.Anamnesa)
	c.CreatedAt, c.UpdatedAt = parseTime(created), parseTime(updated)
	c.Images = []CaseImage{}
	return &c, nil
}

func (s *Store) CreateCase(ctx context.Context, doctorID int64, patientName *string, anamnesa map[string]any) (*Case, error) {
	blob, err := json.Marshal(anamnesa)
	if err != nil {
		return nil, err
	}
	id, ts := NewCaseID(), now()
	_, err = s.db.ExecContext(ctx,
		`INSERT INTO cases (id, doctor_id, patient_name, anamnesa, status, progress, created_at, updated_at)
		 VALUES (?, ?, ?, ?, ?, 0, ?, ?)`,
		id, doctorID, patientName, string(blob), string(StatusDraft), ts, ts)
	if err != nil {
		return nil, err
	}
	return s.GetCase(ctx, id)
}

func (s *Store) GetCase(ctx context.Context, id string) (*Case, error) {
	c, err := scanCase(s.db.QueryRowContext(ctx, `SELECT `+caseColumns+` FROM cases WHERE id = ?`, id))
	if err != nil {
		return nil, err
	}
	images, err := s.listImages(ctx, id)
	if err != nil {
		return nil, err
	}
	c.Images = images
	return c, nil
}

// ListCases returns a doctor's own cases, newest first. Admins pass doctorID = 0 to see all.
func (s *Store) ListCases(ctx context.Context, doctorID int64) ([]*Case, error) {
	query := `SELECT ` + caseColumns + ` FROM cases`
	args := []any{}
	if doctorID > 0 {
		query += ` WHERE doctor_id = ?`
		args = append(args, doctorID)
	}
	query += ` ORDER BY created_at DESC`

	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	cases := []*Case{}
	for rows.Next() {
		c, err := scanCase(rows)
		if err != nil {
			return nil, err
		}
		cases = append(cases, c)
	}
	return cases, rows.Err()
}

func (s *Store) listImages(ctx context.Context, caseID string) ([]CaseImage, error) {
	rows, err := s.db.QueryContext(ctx,
		`SELECT view_key, path FROM case_images WHERE case_id = ? ORDER BY id`, caseID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	images := []CaseImage{}
	for rows.Next() {
		var img CaseImage
		if err := rows.Scan(&img.ViewKey, &img.Path); err != nil {
			return nil, err
		}
		images = append(images, img)
	}
	return images, rows.Err()
}

// UpsertImage replaces the photo in a view slot, so re-uploading a view is idempotent.
func (s *Store) UpsertImage(ctx context.Context, caseID, viewKey, path string) error {
	return s.tx(ctx, func(tx *sql.Tx) error {
		if _, err := tx.ExecContext(ctx,
			`INSERT INTO case_images (case_id, view_key, path) VALUES (?, ?, ?)
			 ON CONFLICT(case_id, view_key) DO UPDATE SET path = excluded.path`,
			caseID, viewKey, path); err != nil {
			return err
		}
		_, err := tx.ExecContext(ctx,
			`UPDATE cases SET status = CASE WHEN status = 'draft' THEN 'uploaded' ELSE status END,
			                  updated_at = ? WHERE id = ?`, now(), caseID)
		return err
	})
}

// CaseUpdate carries only the fields a particular transition touches.
type CaseUpdate struct {
	Status           *CaseStatus
	Progress         *int
	Stage            *string
	DatasetID        *string
	Error            *string
	DiagnosisMD      *string
	RecommendationMD *string
	SanityMD         *string
	ClearError       bool
	ClearDataset     bool
}

func (s *Store) UpdateCase(ctx context.Context, id string, up CaseUpdate) error {
	sets := []string{"updated_at = ?"}
	args := []any{now()}

	add := func(column string, value any) {
		sets = append(sets, column+" = ?")
		args = append(args, value)
	}
	if up.Status != nil {
		add("status", string(*up.Status))
	}
	if up.Progress != nil {
		add("progress", *up.Progress)
	}
	if up.Stage != nil {
		add("stage", *up.Stage)
	}
	if up.DatasetID != nil {
		add("dataset_id", *up.DatasetID)
	}
	if up.ClearDataset {
		add("dataset_id", nil)
	}
	if up.Error != nil {
		add("error", *up.Error)
	}
	if up.ClearError {
		add("error", nil)
	}
	if up.DiagnosisMD != nil {
		add("diagnosis_md", *up.DiagnosisMD)
	}
	if up.RecommendationMD != nil {
		add("recommendation_md", *up.RecommendationMD)
	}
	if up.SanityMD != nil {
		add("sanity_md", *up.SanityMD)
	}

	args = append(args, id)
	query := `UPDATE cases SET `
	for i, set := range sets {
		if i > 0 {
			query += ", "
		}
		query += set
	}
	query += ` WHERE id = ?`

	res, err := s.db.ExecContext(ctx, query, args...)
	if err != nil {
		return err
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return ErrNotFound
	}
	return nil
}

func (s *Store) DeleteCase(ctx context.Context, id string) error {
	res, err := s.db.ExecContext(ctx, `DELETE FROM cases WHERE id = ?`, id)
	if err != nil {
		return err
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return ErrNotFound
	}
	return nil
}

// ResetStaleJobs marks cases that were mid-analysis when the process died as failed.
// Without it a crash leaves a case polling "running" forever.
func (s *Store) ResetStaleJobs(ctx context.Context) (int64, error) {
	res, err := s.db.ExecContext(ctx,
		`UPDATE cases SET status = 'failed', stage = 'Gagal',
		        error = 'Analisis terhenti karena server dimulai ulang', updated_at = ?
		 WHERE status IN ('queued', 'running')`, now())
	if err != nil {
		return 0, err
	}
	return res.RowsAffected()
}
