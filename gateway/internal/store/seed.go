package store

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// SeedSpec mirrors assets/seed/demo_cases.json — the single source of truth shared with the
// Python eval harness, so the cases the app ships and the cases the evals score are the same
// patients.
type SeedSpec struct {
	Accounts []SeedAccount `json:"accounts"`
	Cases    []SeedCase    `json:"cases"`
}

type SeedAccount struct {
	Email    string `json:"email"`
	Name     string `json:"name"`
	Role     Role   `json:"role"`
	Password string `json:"password"`
}

type SeedCase struct {
	ID          string            `json:"id"`
	Dataset     string            `json:"dataset"`
	PatientName string            `json:"patient_name"`
	Anamnesa    map[string]string `json:"anamnesa"`
}

// LoadSeedSpec reads the shared demo definition.
func LoadSeedSpec(dir string) (*SeedSpec, error) {
	raw, err := os.ReadFile(filepath.Join(dir, "demo_cases.json"))
	if err != nil {
		return nil, fmt.Errorf("read seed spec: %w", err)
	}
	var spec SeedSpec
	if err := json.Unmarshal(raw, &spec); err != nil {
		return nil, fmt.Errorf("parse seed spec: %w", err)
	}
	return &spec, nil
}

// SeedResult reports what a seed run actually changed, so the caller can log it honestly.
type SeedResult struct {
	AccountsCreated []string
	CasesCreated    []string
}

// Seed creates any missing demo accounts and cases. It is **idempotent**: existing accounts
// (matched by email) and existing cases (matched by deterministic id) are left untouched, so
// it is safe to run on every boot.
//
// The advisory markdown for each demo case is loaded from `<dir>/advisory/<case-id>-*.md`
// when present. Those files are the committed output of a real model run, which is what lets
// a fresh clone show a complete case with **zero API calls** — the database itself is not
// committed, so seeding is the only place they can be restored from.
func (s *Store) Seed(ctx context.Context, dir string, hash func(string) (string, error)) (*SeedResult, error) {
	spec, err := LoadSeedSpec(dir)
	if err != nil {
		return nil, err
	}
	result := &SeedResult{}

	var doctorID int64
	for _, acct := range spec.Accounts {
		user, err := s.GetUserByEmail(ctx, acct.Email)
		switch {
		case err == nil:
			// already present
		case err == ErrNotFound:
			pw, hashErr := hash(acct.Password)
			if hashErr != nil {
				return nil, hashErr
			}
			role := acct.Role
			if !role.Valid() {
				role = RoleDoctor
			}
			user, err = s.CreateUser(ctx, acct.Email, acct.Name, role, pw)
			if err != nil {
				return nil, err
			}
			result.AccountsCreated = append(result.AccountsCreated, acct.Email)
		default:
			return nil, err
		}
		if user.Role == RoleDoctor && doctorID == 0 {
			doctorID = user.ID
		}
	}

	if doctorID == 0 {
		return result, nil // no doctor account to own the demo history
	}

	for _, demo := range spec.Cases {
		if _, err := s.GetCase(ctx, demo.ID); err == nil {
			continue // already seeded
		} else if err != ErrNotFound {
			return nil, err
		}
		if err := s.insertDemoCase(ctx, dir, demo, doctorID); err != nil {
			return nil, err
		}
		result.CasesCreated = append(result.CasesCreated, demo.ID)
	}
	return result, nil
}

func (s *Store) insertDemoCase(ctx context.Context, dir string, demo SeedCase, doctorID int64) error {
	anamnesa, err := json.Marshal(demo.Anamnesa)
	if err != nil {
		return err
	}
	ts := now()
	name := demo.PatientName

	diagnosis := readAdvisory(dir, demo.ID, "diagnosis")
	recommendation := readAdvisory(dir, demo.ID, "recommendation")
	sanity := readAdvisory(dir, demo.ID, "sanity")

	_, err = s.db.ExecContext(ctx,
		`INSERT INTO cases (id, doctor_id, patient_name, anamnesa, status, progress, stage,
		                    dataset_id, diagnosis_md, recommendation_md, sanity_md,
		                    created_at, updated_at)
		 VALUES (?, ?, ?, ?, 'done', 100, 'Selesai', ?, ?, ?, ?, ?, ?)`,
		demo.ID, doctorID, &name, string(anamnesa), demo.Dataset,
		diagnosis, recommendation, sanity, ts, ts)
	return err
}

// readAdvisory returns nil when the file is absent, which makes the committed markdown
// optional: a clone without it still gets a working case, just with an empty advisory card.
func readAdvisory(dir, caseID, kind string) *string {
	for _, name := range []string{
		fmt.Sprintf("%s-%s.md", caseID, kind),
		fmt.Sprintf("%s.md", caseID), // legacy single-file layout (diagnosis only)
	} {
		if kind != "diagnosis" && name == fmt.Sprintf("%s.md", caseID) {
			continue
		}
		raw, err := os.ReadFile(filepath.Join(dir, "advisory", name))
		if err == nil && len(raw) > 0 {
			text := string(raw)
			return &text
		}
	}
	return nil
}
