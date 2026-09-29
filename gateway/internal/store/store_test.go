package store

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func newStore(t *testing.T) *Store {
	t.Helper()
	st, err := Open(filepath.Join(t.TempDir(), "test.db"))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	t.Cleanup(func() { _ = st.Close() })
	return st
}

func mustUser(t *testing.T, st *Store, email string, role Role) *User {
	t.Helper()
	u, err := st.CreateUser(context.Background(), email, "Name", role, "hash")
	if err != nil {
		t.Fatalf("create user: %v", err)
	}
	return u
}

func TestEmailsAreStoredNormalized(t *testing.T) {
	st := newStore(t)
	u := mustUser(t, st, "  Doctor@Example.IO ", RoleDoctor)
	if u.Email != "doctor@example.io" {
		t.Errorf("email = %q", u.Email)
	}
	if _, err := st.GetUserByEmail(context.Background(), "DOCTOR@example.io"); err != nil {
		t.Errorf("lookup should be case-insensitive: %v", err)
	}
}

func TestDuplicateEmailIsReportedDistinctly(t *testing.T) {
	st := newStore(t)
	mustUser(t, st, "a@x.io", RoleDoctor)
	_, err := st.CreateUser(context.Background(), "A@X.io", "Other", RoleDoctor, "hash")
	if !errors.Is(err, ErrEmailTaken) {
		t.Errorf("got %v, want ErrEmailTaken", err)
	}
}

func TestMissingRowsReportNotFound(t *testing.T) {
	st := newStore(t)
	if _, err := st.GetUser(context.Background(), 999); !errors.Is(err, ErrNotFound) {
		t.Errorf("GetUser: %v", err)
	}
	if _, err := st.GetCase(context.Background(), "nope"); !errors.Is(err, ErrNotFound) {
		t.Errorf("GetCase: %v", err)
	}
	if err := st.DeleteUser(context.Background(), 999); !errors.Is(err, ErrNotFound) {
		t.Errorf("DeleteUser: %v", err)
	}
}

func TestPartialUserUpdateLeavesOtherFieldsAlone(t *testing.T) {
	st := newStore(t)
	u := mustUser(t, st, "a@x.io", RoleDoctor)

	newName := "Renamed"
	updated, err := st.UpdateUser(context.Background(), u.ID, UserUpdate{Name: &newName})
	if err != nil {
		t.Fatal(err)
	}
	if updated.Name != "Renamed" || updated.Role != RoleDoctor || !updated.IsActive {
		t.Errorf("unexpected state after partial update: %+v", updated)
	}
}

func TestCountAdminsIgnoresDeactivatedOnes(t *testing.T) {
	st := newStore(t)
	admin := mustUser(t, st, "admin@x.io", RoleAdmin)
	mustUser(t, st, "doc@x.io", RoleDoctor)

	if n, _ := st.CountAdmins(context.Background()); n != 1 {
		t.Fatalf("got %d admins, want 1", n)
	}
	inactive := false
	if _, err := st.UpdateUser(context.Background(), admin.ID, UserUpdate{IsActive: &inactive}); err != nil {
		t.Fatal(err)
	}
	if n, _ := st.CountAdmins(context.Background()); n != 0 {
		t.Errorf("a deactivated admin still counted: %d", n)
	}
}

func TestCaseIDsAreUniqueAndPrefixed(t *testing.T) {
	seen := map[string]bool{}
	for i := 0; i < 200; i++ {
		id := NewCaseID()
		if seen[id] {
			t.Fatalf("duplicate case id %q", id)
		}
		if len(id) < 20 || id[:5] != "case-" {
			t.Fatalf("unexpected id shape %q", id)
		}
		seen[id] = true
	}
}

func TestCaseRoundTripsItsAnamnesa(t *testing.T) {
	st := newStore(t)
	doctor := mustUser(t, st, "a@x.io", RoleDoctor)
	name := "Anak A"

	created, err := st.CreateCase(context.Background(), doctor.ID, &name,
		map[string]any{"lokasi": "Gigi depan atas", "quality": "Ngilu"})
	if err != nil {
		t.Fatal(err)
	}
	loaded, err := st.GetCase(context.Background(), created.ID)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.Anamnesa["lokasi"] != "Gigi depan atas" {
		t.Errorf("anamnesa lost: %+v", loaded.Anamnesa)
	}
	if loaded.Status != StatusDraft || loaded.Progress != 0 {
		t.Errorf("unexpected initial state: %s %d", loaded.Status, loaded.Progress)
	}
	if loaded.Images == nil {
		t.Error("images should be an empty slice, not nil (it is serialized to JSON)")
	}
}

func TestUpsertImageIsIdempotentPerViewSlot(t *testing.T) {
	st := newStore(t)
	doctor := mustUser(t, st, "a@x.io", RoleDoctor)
	kase, _ := st.CreateCase(context.Background(), doctor.ID, nil, nil)

	if err := st.UpsertImage(context.Background(), kase.ID, "up", "x/up.jpg"); err != nil {
		t.Fatal(err)
	}
	if err := st.UpsertImage(context.Background(), kase.ID, "up", "x/up.png"); err != nil {
		t.Fatal(err)
	}
	loaded, _ := st.GetCase(context.Background(), kase.ID)
	if len(loaded.Images) != 1 || loaded.Images[0].Path != "x/up.png" {
		t.Errorf("expected one replaced image, got %+v", loaded.Images)
	}
	if loaded.Status != StatusUploaded {
		t.Errorf("first upload should move draft -> uploaded, got %s", loaded.Status)
	}
}

func TestUpsertImageDoesNotRegressALaterStatus(t *testing.T) {
	st := newStore(t)
	doctor := mustUser(t, st, "a@x.io", RoleDoctor)
	kase, _ := st.CreateCase(context.Background(), doctor.ID, nil, nil)

	done := StatusDone
	if err := st.UpdateCase(context.Background(), kase.ID, CaseUpdate{Status: &done}); err != nil {
		t.Fatal(err)
	}
	if err := st.UpsertImage(context.Background(), kase.ID, "up", "x/up.jpg"); err != nil {
		t.Fatal(err)
	}
	loaded, _ := st.GetCase(context.Background(), kase.ID)
	if loaded.Status != StatusDone {
		t.Errorf("status regressed to %s", loaded.Status)
	}
}

func TestClearErrorAndDatasetAreExplicit(t *testing.T) {
	st := newStore(t)
	doctor := mustUser(t, st, "a@x.io", RoleDoctor)
	kase, _ := st.CreateCase(context.Background(), doctor.ID, nil, nil)

	msg, dataset := "boom", "case-1"
	_ = st.UpdateCase(context.Background(), kase.ID, CaseUpdate{Error: &msg, DatasetID: &dataset})
	_ = st.UpdateCase(context.Background(), kase.ID, CaseUpdate{ClearError: true, ClearDataset: true})

	loaded, _ := st.GetCase(context.Background(), kase.ID)
	if loaded.Error != nil || loaded.DatasetID != nil {
		t.Errorf("clear flags ignored: err=%v dataset=%v", loaded.Error, loaded.DatasetID)
	}
}

func TestDeletingACaseCascadesToItsImages(t *testing.T) {
	st := newStore(t)
	doctor := mustUser(t, st, "a@x.io", RoleDoctor)
	kase, _ := st.CreateCase(context.Background(), doctor.ID, nil, nil)
	_ = st.UpsertImage(context.Background(), kase.ID, "up", "x/up.jpg")

	if err := st.DeleteCase(context.Background(), kase.ID); err != nil {
		t.Fatal(err)
	}
	var n int
	if err := st.DB().QueryRow(`SELECT COUNT(*) FROM case_images WHERE case_id = ?`, kase.ID).Scan(&n); err != nil {
		t.Fatal(err)
	}
	if n != 0 {
		t.Errorf("%d orphaned image rows survived", n)
	}
}

func TestListCasesScopesByDoctorAndOrdersNewestFirst(t *testing.T) {
	st := newStore(t)
	mine := mustUser(t, st, "a@x.io", RoleDoctor)
	theirs := mustUser(t, st, "b@x.io", RoleDoctor)

	first, _ := st.CreateCase(context.Background(), mine.ID, nil, nil)
	second, _ := st.CreateCase(context.Background(), mine.ID, nil, nil)
	_, _ = st.CreateCase(context.Background(), theirs.ID, nil, nil)

	scoped, err := st.ListCases(context.Background(), mine.ID)
	if err != nil {
		t.Fatal(err)
	}
	if len(scoped) != 2 {
		t.Fatalf("got %d cases, want 2", len(scoped))
	}
	if scoped[0].ID != second.ID || scoped[1].ID != first.ID {
		t.Errorf("expected newest first, got %s then %s", scoped[0].ID, scoped[1].ID)
	}

	all, _ := st.ListCases(context.Background(), 0)
	if len(all) != 3 {
		t.Errorf("unscoped list returned %d, want 3", len(all))
	}
}

func TestResetStaleJobsFailsInterruptedRunsOnly(t *testing.T) {
	st := newStore(t)
	doctor := mustUser(t, st, "a@x.io", RoleDoctor)

	running, _ := st.CreateCase(context.Background(), doctor.ID, nil, nil)
	finished, _ := st.CreateCase(context.Background(), doctor.ID, nil, nil)

	run, done := StatusRunning, StatusDone
	_ = st.UpdateCase(context.Background(), running.ID, CaseUpdate{Status: &run})
	_ = st.UpdateCase(context.Background(), finished.ID, CaseUpdate{Status: &done})

	n, err := st.ResetStaleJobs(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if n != 1 {
		t.Errorf("reset %d cases, want 1", n)
	}
	stuck, _ := st.GetCase(context.Background(), running.ID)
	if stuck.Status != StatusFailed || stuck.Error == nil {
		t.Errorf("interrupted case not failed: %+v", stuck.Status)
	}
	untouched, _ := st.GetCase(context.Background(), finished.ID)
	if untouched.Status != StatusDone {
		t.Errorf("a finished case was reset to %s", untouched.Status)
	}
}

func TestValidViewKey(t *testing.T) {
	for _, key := range ViewKeys {
		if !ValidViewKey(key) {
			t.Errorf("%q rejected", key)
		}
	}
	for _, key := range []string{"", "selfie", "UP", "../etc"} {
		if ValidViewKey(key) {
			t.Errorf("%q accepted", key)
		}
	}
}

// --- seeding -----------------------------------------------------------------

func writeSeed(t *testing.T, dir string, spec SeedSpec) {
	t.Helper()
	blob, _ := json.Marshal(spec)
	if err := os.WriteFile(filepath.Join(dir, "demo_cases.json"), blob, 0o600); err != nil {
		t.Fatal(err)
	}
}

func demoSpec() SeedSpec {
	return SeedSpec{
		Accounts: []SeedAccount{
			{Email: "admin@x.io", Name: "Admin", Role: RoleAdmin, Password: "admin123"},
			{Email: "doc@x.io", Name: "Doctor", Role: RoleDoctor, Password: "doctor123"},
		},
		Cases: []SeedCase{
			{ID: "demo-1", Dataset: "set1", PatientName: "Anak A",
				Anamnesa: map[string]string{"lokasi": "Gigi depan atas"}},
		},
	}
}

func identityHash(s string) (string, error) { return "hash:" + s, nil }

func TestSeedCreatesAccountsAndCases(t *testing.T) {
	st := newStore(t)
	dir := t.TempDir()
	writeSeed(t, dir, demoSpec())

	result, err := st.Seed(context.Background(), dir, identityHash)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.AccountsCreated) != 2 || len(result.CasesCreated) != 1 {
		t.Fatalf("unexpected seed result: %+v", result)
	}
	kase, err := st.GetCase(context.Background(), "demo-1")
	if err != nil {
		t.Fatal(err)
	}
	if kase.Status != StatusDone || kase.DatasetID == nil || *kase.DatasetID != "set1" {
		t.Errorf("demo case not ready to view: %+v", kase.Status)
	}
}

func TestSeedIsIdempotent(t *testing.T) {
	st := newStore(t)
	dir := t.TempDir()
	writeSeed(t, dir, demoSpec())

	if _, err := st.Seed(context.Background(), dir, identityHash); err != nil {
		t.Fatal(err)
	}
	second, err := st.Seed(context.Background(), dir, identityHash)
	if err != nil {
		t.Fatal(err)
	}
	if len(second.AccountsCreated) != 0 || len(second.CasesCreated) != 0 {
		t.Errorf("second run duplicated data: %+v", second)
	}
	users, _ := st.ListUsers(context.Background())
	if len(users) != 2 {
		t.Errorf("got %d users after two seeds, want 2", len(users))
	}
}

func TestSeedAttachesCommittedAdvisoryMarkdownWhenPresent(t *testing.T) {
	st := newStore(t)
	dir := t.TempDir()
	writeSeed(t, dir, demoSpec())
	if err := os.MkdirAll(filepath.Join(dir, "advisory"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "advisory", "demo-1-diagnosis.md"),
		[]byte("# Diagnosis nyata"), 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := st.Seed(context.Background(), dir, identityHash); err != nil {
		t.Fatal(err)
	}
	kase, _ := st.GetCase(context.Background(), "demo-1")
	if kase.DiagnosisMD == nil || *kase.DiagnosisMD != "# Diagnosis nyata" {
		t.Errorf("committed advisory not loaded: %+v", kase.DiagnosisMD)
	}
	// Absent files are optional — the case still exists, just without that card.
	if kase.RecommendationMD != nil {
		t.Errorf("expected no recommendation, got %q", *kase.RecommendationMD)
	}
}

func TestSeedWithoutASpecFileIsAnError(t *testing.T) {
	st := newStore(t)
	if _, err := st.Seed(context.Background(), t.TempDir(), identityHash); err == nil {
		t.Error("expected an error when the seed file is missing")
	}
}
