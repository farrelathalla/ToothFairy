// Package mlclient talks to the Python ML service.
//
// Two calls, shaped by how long they take and what they can report:
//
//   - Analyze streams NDJSON. The vision pipeline runs for tens of seconds to minutes and
//     emits meaningful stages, so the client decodes them line by line and hands each to a
//     callback. That is what lets the gateway persist real progress instead of a fake spinner,
//     with no job state duplicated on the Python side.
//   - Advisory is an ordinary request/response.
//
// Every request carries the shared internal key and a context deadline; the ML service is
// expected to sit on a private network, and the key is the second lock on that door.
package mlclient

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// maxLineBytes bounds one NDJSON event. A malformed upstream must not be able to make the
// gateway allocate without limit.
const maxLineBytes = 1 << 20

type Client struct {
	baseURL     string
	internalKey string
	http        *http.Client
}

func New(baseURL, internalKey string, timeout time.Duration) *Client {
	return &Client{
		baseURL:     strings.TrimRight(baseURL, "/"),
		internalKey: internalKey,
		http: &http.Client{
			Timeout: timeout,
			Transport: &http.Transport{
				MaxIdleConnsPerHost: 4,
				// The analyze response streams, so response header timeouts are the only
				// safe place to be strict.
				ResponseHeaderTimeout: 60 * time.Second,
			},
		},
	}
}

type AnalyzeRequest struct {
	CaseID string            `json:"case_id"`
	Images map[string]string `json:"images"` // view key -> absolute path
}

type AdvisoryRequest struct {
	CaseID      string         `json:"case_id"`
	DatasetID   string         `json:"dataset_id"`
	PatientName string         `json:"patient_name,omitempty"`
	Anamnesa    map[string]any `json:"anamnesa"`
}

type AdvisoryResponse struct {
	DiagnosisMD      string         `json:"diagnosis_md"`
	RecommendationMD string         `json:"recommendation_md"`
	SanityMD         string         `json:"sanity_md"`
	Meta             map[string]any `json:"meta"`
}

type Health struct {
	OK            bool   `json:"ok"`
	Service       string `json:"service"`
	MockInference bool   `json:"mock_inference"`
	LLMEnabled    bool   `json:"llm_enabled"`
	RAGEnabled    bool   `json:"rag_enabled"`
	Model         string `json:"model"`
}

// ProgressFunc receives each progress event as it arrives.
type ProgressFunc func(pct int, stage string)

type event struct {
	Type      string `json:"type"`
	Pct       int    `json:"pct"`
	Stage     string `json:"stage"`
	DatasetID string `json:"dataset_id"`
	Message   string `json:"message"`
}

func (c *Client) request(ctx context.Context, method, path string, body any) (*http.Request, error) {
	var reader io.Reader
	if body != nil {
		blob, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		reader = bytes.NewReader(blob)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, reader)
	if err != nil {
		return nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.internalKey != "" {
		req.Header.Set("X-Internal-Key", c.internalKey)
	}
	return req, nil
}

// Analyze runs the vision pipeline and returns the dataset id it wrote.
func (c *Client) Analyze(ctx context.Context, in AnalyzeRequest, onProgress ProgressFunc) (string, error) {
	req, err := c.request(ctx, http.MethodPost, "/internal/analyze", in)
	if err != nil {
		return "", err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return "", fmt.Errorf("ml service unreachable: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("ml service returned %s: %s", resp.Status, readSnippet(resp.Body))
	}

	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 64*1024), maxLineBytes)

	var datasetID string
	for scanner.Scan() {
		line := bytes.TrimSpace(scanner.Bytes())
		if len(line) == 0 {
			continue
		}
		var ev event
		if err := json.Unmarshal(line, &ev); err != nil {
			continue // a malformed line is not worth failing an otherwise healthy run
		}
		switch ev.Type {
		case "progress":
			if onProgress != nil {
				onProgress(ev.Pct, ev.Stage)
			}
		case "result":
			datasetID = ev.DatasetID
		case "error":
			return "", fmt.Errorf("analysis failed: %s", ev.Message)
		}
	}
	if err := scanner.Err(); err != nil {
		return "", fmt.Errorf("reading analysis stream: %w", err)
	}
	if datasetID == "" {
		// The stream ended without a terminal event — treat a silent truncation as failure
		// rather than marking the case done with no results.
		return "", fmt.Errorf("analysis stream ended without a result")
	}
	return datasetID, nil
}

// Advisory runs the LLM/RAG graph for an already-analysed case.
func (c *Client) Advisory(ctx context.Context, in AdvisoryRequest) (*AdvisoryResponse, error) {
	req, err := c.request(ctx, http.MethodPost, "/internal/advisory", in)
	if err != nil {
		return nil, err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("ml service unreachable: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("ml service returned %s: %s", resp.Status, readSnippet(resp.Body))
	}
	var out AdvisoryResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, fmt.Errorf("decoding advisory response: %w", err)
	}
	return &out, nil
}

// Health probes the ML service. Used by the gateway's own /health so an operator sees one
// answer for the whole system.
func (c *Client) Health(ctx context.Context) (*Health, error) {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()

	req, err := c.request(ctx, http.MethodGet, "/health", nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("ml service returned %s", resp.Status)
	}
	var out Health
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return &out, nil
}

// readSnippet bounds how much of an error body is echoed into a log line or an error string.
func readSnippet(r io.Reader) string {
	buf, _ := io.ReadAll(io.LimitReader(r, 512))
	return strings.TrimSpace(string(buf))
}
