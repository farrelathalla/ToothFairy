// Package jobs runs case analyses off the request path.
//
// A bounded worker pool drains a bounded queue. Both bounds matter: the vision models are the
// scarce resource, so admitting unlimited work would only convert a queue into thrashing and
// turn a slow response into a timeout for everyone. When the queue is full, `Enqueue` fails
// fast and the caller gets 503 — an honest "try again shortly" rather than a request that
// hangs.
//
// Each job owns its own context with a generous deadline and writes progress straight to the
// store, so a browser polling `/cases/{id}/status` sees the pipeline's real stages. Panics are
// recovered per job: one bad case must never take the pool down.
package jobs

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"path/filepath"
	"runtime/debug"
	"sync"
	"time"

	"github.com/farrelathalla/toothfairy/gateway/internal/mlclient"
	"github.com/farrelathalla/toothfairy/gateway/internal/store"
)

// ErrQueueFull is returned when the pool is saturated.
var ErrQueueFull = errors.New("antrean analisis penuh")

type Runner struct {
	store     *store.Store
	ml        *mlclient.Client
	uploadDir string
	timeout   time.Duration
	log       *slog.Logger

	queue chan string
	wg    sync.WaitGroup
	stop  chan struct{}
	once  sync.Once
}

func NewRunner(st *store.Store, ml *mlclient.Client, uploadDir string, timeout time.Duration, log *slog.Logger) *Runner {
	return &Runner{
		store: st, ml: ml, uploadDir: uploadDir, timeout: timeout, log: log,
		stop: make(chan struct{}),
	}
}

// Start launches `workers` goroutines draining a queue of `size`.
func (r *Runner) Start(workers, size int) {
	if workers < 1 {
		workers = 1
	}
	if size < 1 {
		size = 1
	}
	r.queue = make(chan string, size)
	for i := 0; i < workers; i++ {
		r.wg.Add(1)
		go r.worker(i)
	}
	r.log.Info("job runner started", "workers", workers, "queue_size", size)
}

// Shutdown stops accepting work and waits for in-flight jobs to finish.
func (r *Runner) Shutdown(ctx context.Context) {
	r.once.Do(func() { close(r.stop) })

	done := make(chan struct{})
	go func() {
		r.wg.Wait()
		close(done)
	}()
	select {
	case <-done:
	case <-ctx.Done():
		r.log.Warn("shutdown timed out with jobs still running")
	}
}

// Enqueue schedules a case, marking it queued so the UI reflects it immediately.
func (r *Runner) Enqueue(ctx context.Context, caseID string) error {
	queued, zero := store.StatusQueued, 0
	stage := "Menunggu antrean"
	if err := r.store.UpdateCase(ctx, caseID, store.CaseUpdate{
		Status: &queued, Progress: &zero, Stage: &stage,
		ClearError: true, ClearDataset: true,
	}); err != nil {
		return err
	}

	select {
	case r.queue <- caseID:
		return nil
	default:
		// Roll the case back so it does not sit "queued" for work that was never accepted.
		failed := store.StatusFailed
		msg := ErrQueueFull.Error()
		failStage := "Gagal"
		_ = r.store.UpdateCase(ctx, caseID, store.CaseUpdate{
			Status: &failed, Error: &msg, Stage: &failStage,
		})
		return ErrQueueFull
	}
}

func (r *Runner) worker(id int) {
	defer r.wg.Done()
	for {
		select {
		case <-r.stop:
			return
		case caseID := <-r.queue:
			r.runSafely(caseID, id)
		}
	}
}

func (r *Runner) runSafely(caseID string, worker int) {
	defer func() {
		if p := recover(); p != nil {
			r.log.Error("job panicked", "case_id", caseID, "panic", p,
				"stack", string(debug.Stack()))
			r.fail(caseID, fmt.Errorf("kesalahan internal saat analisis"))
		}
	}()

	ctx, cancel := context.WithTimeout(context.Background(), r.timeout)
	defer cancel()

	start := time.Now()
	if err := r.run(ctx, caseID); err != nil {
		r.log.Error("job failed", "case_id", caseID, "worker", worker, "err", err)
		r.fail(caseID, err)
		return
	}
	r.log.Info("job done", "case_id", caseID, "worker", worker,
		"duration_s", time.Since(start).Seconds())
}

func (r *Runner) run(ctx context.Context, caseID string) error {
	kase, err := r.store.GetCase(ctx, caseID)
	if err != nil {
		return err
	}
	if len(kase.Images) == 0 {
		return errors.New("kasus tidak memiliki gambar")
	}

	running, zero := store.StatusRunning, 0
	stage := "Memulai analisis"
	if err := r.store.UpdateCase(ctx, caseID, store.CaseUpdate{
		Status: &running, Progress: &zero, Stage: &stage, ClearError: true,
	}); err != nil {
		return err
	}

	images := make(map[string]string, len(kase.Images))
	for _, img := range kase.Images {
		images[img.ViewKey] = filepath.Join(r.uploadDir, filepath.FromSlash(img.Path))
	}

	// Progress writes are best-effort: losing one is cosmetic, and failing the analysis
	// because a status write lost a race would not be.
	onProgress := func(pct int, stageText string) {
		p, s := pct, stageText
		if err := r.store.UpdateCase(ctx, caseID, store.CaseUpdate{Progress: &p, Stage: &s}); err != nil {
			r.log.Warn("progress write failed", "case_id", caseID, "err", err)
		}
	}

	datasetID, err := r.ml.Analyze(ctx, mlclient.AnalyzeRequest{CaseID: caseID, Images: images}, onProgress)
	if err != nil {
		return err
	}

	advisoryStage := "Menyusun diagnosis"
	ninetyFive := 95
	_ = r.store.UpdateCase(ctx, caseID, store.CaseUpdate{
		DatasetID: &datasetID, Stage: &advisoryStage, Progress: &ninetyFive,
	})

	update := store.CaseUpdate{DatasetID: &datasetID}
	advisory, err := r.ml.Advisory(ctx, mlclient.AdvisoryRequest{
		CaseID:      caseID,
		DatasetID:   datasetID,
		PatientName: deref(kase.PatientName),
		Anamnesa:    kase.Anamnesa,
	})
	if err != nil {
		// The clinically valuable work — detection and the 3D reconstruction — already
		// succeeded and is on disk. Losing the advisory text must not discard it, so the
		// case completes with an empty advisory card and the reason recorded.
		r.log.Warn("advisory failed, completing case without it", "case_id", caseID, "err", err)
		note := "Analisis citra selesai; catatan klinis otomatis tidak tersedia."
		update.Error = &note
	} else {
		update.DiagnosisMD = &advisory.DiagnosisMD
		update.RecommendationMD = &advisory.RecommendationMD
		update.SanityMD = &advisory.SanityMD
		if advisory.Meta != nil {
			r.log.Info("advisory complete", "case_id", caseID,
				"llm_enabled", advisory.Meta["llm_enabled"], "sanity_ok", advisory.Meta["sanity_ok"])
		}
	}

	done, hundred := store.StatusDone, 100
	doneStage := "Selesai"
	update.Status = &done
	update.Progress = &hundred
	update.Stage = &doneStage
	return r.store.UpdateCase(ctx, caseID, update)
}

func (r *Runner) fail(caseID string, cause error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	failed := store.StatusFailed
	stage := "Gagal"
	msg := cause.Error()
	if err := r.store.UpdateCase(ctx, caseID, store.CaseUpdate{
		Status: &failed, Stage: &stage, Error: &msg,
	}); err != nil {
		r.log.Error("could not record job failure", "case_id", caseID, "err", err)
	}
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
