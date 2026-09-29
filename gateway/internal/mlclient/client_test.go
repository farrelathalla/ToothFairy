package mlclient

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func stub(t *testing.T, handler http.HandlerFunc) *Client {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	return New(server.URL, "s3cret", 5*time.Second)
}

func TestAnalyzeReportsProgressThenReturnsTheDatasetID(t *testing.T) {
	client := stub(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w,
			`{"type":"progress","pct":10,"stage":"Menyiapkan gambar"}`+"\n"+
				`{"type":"progress","pct":60,"stage":"Grading karies"}`+"\n"+
				`{"type":"result","dataset_id":"case-42"}`+"\n")
	})

	var seen []int
	id, err := client.Analyze(context.Background(),
		AnalyzeRequest{CaseID: "case-42", Images: map[string]string{"up": "/tmp/up.jpg"}},
		func(pct int, stage string) { seen = append(seen, pct) })
	if err != nil {
		t.Fatalf("analyze: %v", err)
	}
	if id != "case-42" {
		t.Errorf("dataset id = %q", id)
	}
	if len(seen) != 2 || seen[0] != 10 || seen[1] != 60 {
		t.Errorf("progress events = %v", seen)
	}
}

func TestAnalyzeSendsTheInternalKey(t *testing.T) {
	var got string
	client := stub(t, func(w http.ResponseWriter, r *http.Request) {
		got = r.Header.Get("X-Internal-Key")
		_, _ = io.WriteString(w, `{"type":"result","dataset_id":"x"}`+"\n")
	})
	if _, err := client.Analyze(context.Background(), AnalyzeRequest{CaseID: "x"}, nil); err != nil {
		t.Fatal(err)
	}
	if got != "s3cret" {
		t.Errorf("internal key header = %q", got)
	}
}

func TestAnalyzeSurfacesATerminalErrorEvent(t *testing.T) {
	client := stub(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, `{"type":"error","message":"bobot model tidak ditemukan"}`+"\n")
	})
	_, err := client.Analyze(context.Background(), AnalyzeRequest{CaseID: "x"}, nil)
	if err == nil || !strings.Contains(err.Error(), "bobot model") {
		t.Errorf("got %v", err)
	}
}

func TestAnalyzeTreatsATruncatedStreamAsFailure(t *testing.T) {
	// Progress but no terminal event: marking the case done here would claim results that
	// were never written.
	client := stub(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, `{"type":"progress","pct":50,"stage":"Deteksi"}`+"\n")
	})
	if _, err := client.Analyze(context.Background(), AnalyzeRequest{CaseID: "x"}, nil); err == nil {
		t.Error("a stream with no result was accepted")
	}
}

func TestAnalyzeSkipsMalformedLinesButKeepsGoing(t *testing.T) {
	client := stub(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w,
			"not json\n"+
				`{"type":"progress","pct":30,"stage":"Deteksi"}`+"\n"+
				"\n"+
				`{"type":"result","dataset_id":"case-7"}`+"\n")
	})
	var seen int
	id, err := client.Analyze(context.Background(), AnalyzeRequest{CaseID: "x"},
		func(pct int, _ string) { seen = pct })
	if err != nil {
		t.Fatalf("analyze: %v", err)
	}
	if id != "case-7" || seen != 30 {
		t.Errorf("id=%q lastProgress=%d", id, seen)
	}
}

func TestAnalyzeReportsAnUpstreamHTTPError(t *testing.T) {
	client := stub(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		_, _ = io.WriteString(w, `{"detail":"Kunci internal tidak valid"}`)
	})
	_, err := client.Analyze(context.Background(), AnalyzeRequest{CaseID: "x"}, nil)
	if err == nil || !strings.Contains(err.Error(), "401") {
		t.Errorf("got %v", err)
	}
}

func TestAnalyzeHonoursContextCancellation(t *testing.T) {
	client := stub(t, func(w http.ResponseWriter, r *http.Request) {
		w.(http.Flusher).Flush()
		<-r.Context().Done()
	})
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	if _, err := client.Analyze(ctx, AnalyzeRequest{CaseID: "x"}, nil); err == nil {
		t.Error("expected the cancelled request to fail")
	}
}

func TestAdvisoryDecodesAllThreeFields(t *testing.T) {
	client := stub(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, `{"diagnosis_md":"# D","recommendation_md":"# R",
			"sanity_md":"# S","meta":{"llm_enabled":true}}`)
	})
	out, err := client.Advisory(context.Background(), AdvisoryRequest{CaseID: "x", DatasetID: "x"})
	if err != nil {
		t.Fatal(err)
	}
	if out.DiagnosisMD != "# D" || out.RecommendationMD != "# R" || out.SanityMD != "# S" {
		t.Errorf("unexpected payload: %+v", out)
	}
	if out.Meta["llm_enabled"] != true {
		t.Errorf("meta lost: %+v", out.Meta)
	}
}

func TestAdvisoryReportsAnUpstreamFailure(t *testing.T) {
	client := stub(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})
	if _, err := client.Advisory(context.Background(), AdvisoryRequest{CaseID: "x"}); err == nil {
		t.Error("expected an error")
	}
}

func TestUnreachableServiceIsReportedClearly(t *testing.T) {
	client := New("http://127.0.0.1:1", "", time.Second)
	_, err := client.Analyze(context.Background(), AnalyzeRequest{CaseID: "x"}, nil)
	if err == nil || !strings.Contains(err.Error(), "unreachable") {
		t.Errorf("got %v", err)
	}
}
