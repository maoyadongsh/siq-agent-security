package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

// Client is the control-plane HTTP client. Endpoint contract (Phase 0, server
// implementation lives in apps/control-api, TBD):
//
//	POST /edge/v1/register            body: RegisterRequest
//	POST /edge/v1/heartbeat           body: {device_identity, version, sent_at}
//	GET  /edge/v1/tasks?device_identity=...
//	POST /edge/v1/tasks/{id}/receipt  body: Receipt
//
// All requests carry the X-Edge-Version header; requests after registration
// carry Authorization: Bearer <secret>.
type Client struct {
	base     string
	identity string
	secret   string
	version  string
	http     *http.Client
}

// ClientConfig configures a Client.
type ClientConfig struct {
	ControlPlaneURL string
	DeviceIdentity  string
	Secret          string
	Version         string // sent as X-Edge-Version and in register.version
	HTTPTimeout     time.Duration
}

// NewClient builds a Client (default HTTP timeout 30s).
func NewClient(cfg ClientConfig) *Client {
	if cfg.HTTPTimeout <= 0 {
		cfg.HTTPTimeout = 30 * time.Second
	}
	return &Client{
		base:     strings.TrimRight(cfg.ControlPlaneURL, "/"),
		identity: cfg.DeviceIdentity,
		secret:   cfg.Secret,
		version:  cfg.Version,
		http:     &http.Client{Timeout: cfg.HTTPTimeout},
	}
}

// RegisterRequest is the POST /edge/v1/register body.
type RegisterRequest struct {
	EnrollmentCode string         `json:"enrollment_code"`
	DeviceIdentity string         `json:"device_identity"`
	PublicKeyPEM   string         `json:"public_key_pem"`
	Version        string         `json:"version"`
	Capabilities   map[string]any `json:"capabilities"`
}

// RegisterResponse is the POST /edge/v1/register response (control-api 实际契约).
type RegisterResponse struct {
	EdgeAgentID           string `json:"edge_agent_id"`
	DeviceSecret          string `json:"device_secret"`
	ControlPlanePublicKey string `json:"control_plane_public_key"`
	EnvironmentID         string `json:"environment_id"`
}

// Register enrolls the device. The caller persists the returned secret into
// the local state file (mode 0600).
func (c *Client) Register(ctx context.Context, code, identity, pubPEM string, caps map[string]any) (*RegisterResponse, error) {
	body := RegisterRequest{
		EnrollmentCode: code,
		DeviceIdentity: identity,
		PublicKeyPEM:   pubPEM,
		Version:        c.version,
		Capabilities:   caps,
	}
	var out RegisterResponse
	if err := c.do(ctx, http.MethodPost, "/edge/v1/register", body, &out, 3); err != nil {
		return nil, err
	}
	return &out, nil
}

// HeartbeatOnce posts one heartbeat.
func (c *Client) HeartbeatOnce(ctx context.Context) error {
	body := map[string]any{
		"device_identity": c.identity,
		"version":         c.version,
		"sent_at":         time.Now().UTC().Format(time.RFC3339),
	}
	var out map[string]any
	return c.do(ctx, http.MethodPost, "/edge/v1/heartbeat", body, &out, 3)
}

// RunHeartbeatLoop beats every interval (default 30s) and applies exponential
// backoff (doubling, capped at maxBackoff) on failures.
func (c *Client) RunHeartbeatLoop(ctx context.Context, interval, maxBackoff time.Duration) error {
	if interval <= 0 {
		interval = 30 * time.Second
	}
	if maxBackoff <= 0 {
		maxBackoff = 15 * time.Minute
	}
	backoff := interval
	for {
		if err := c.HeartbeatOnce(ctx); err != nil {
			log.Printf("heartbeat failed: %v (backing off %s)", err, backoff)
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(backoff):
			}
			backoff *= 2
			if backoff > maxBackoff {
				backoff = maxBackoff
			}
			continue
		}
		backoff = interval
		log.Printf("heartbeat ok (%s)", c.identity)
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(interval):
		}
	}
}


// FetchTasks pulls the pending tasks for this device.
func (c *Client) FetchTasks(ctx context.Context, deviceIdentity string) ([]*Task, error) {
	// 设备身份经 X-Edge-Identity 头传递（控制面契约），响应为裸任务列表
	var out []*Task
	if err := c.do(ctx, http.MethodGet, "/edge/v1/tasks", nil, &out, 2); err != nil {
		return nil, err
	}
	if out == nil {
		out = []*Task{}
	}
	return out, nil
}

// Receipt is posted after task execution (POST /edge/v1/tasks/{id}/receipt).
type Receipt struct {
	TaskID         string   `json:"task_id"`
	DeviceIdentity string   `json:"device_identity"`
	Status         string   `json:"status"` // succeeded | failed | unsupported
	ErrorCode      string   `json:"error_code,omitempty"`
	ErrorMessage   string   `json:"error_message,omitempty"`
	CandidateCount int      `json:"candidate_count"`
	EvidenceCount  int      `json:"evidence_count"`
	EvidenceIDs    []string `json:"evidence_ids,omitempty"`
	Cursor         string   `json:"cursor,omitempty"`
	Truncated      bool     `json:"truncated,omitempty"`
	CompletedAt    string   `json:"completed_at"`
}

// PostReceipt reports a task outcome to the control plane.
func (c *Client) PostReceipt(ctx context.Context, taskID string, r *Receipt) error {
	path := "/edge/v1/tasks/" + url.PathEscape(taskID) + "/receipt"
	return c.do(ctx, http.MethodPost, path, r, nil, 3)
}

// retryableError marks failures worth retrying (network errors, 429, 5xx).
type retryableError struct{ err error }

func (e *retryableError) Error() string { return e.err.Error() }
func (e *retryableError) Unwrap() error { return e.err }

func isRetryable(err error) bool {
	var r *retryableError
	return errors.As(err, &r)
}

// backoffDelay returns 2^attempt seconds, capped at 32s.
func backoffDelay(attempt int) time.Duration {
	exp := attempt
	if exp > 5 {
		exp = 5
	}
	return time.Duration(1<<exp) * time.Second
}

// UploadBatch posts discovered candidates and evidence to the control plane
// (design doc §9.3 data flow: E -> C 上传候选资产与证据摘要). The batch is
// sealed (signature/collector_id) before upload; permission facts are empty
// in Phase 1 (connectors do not emit them yet).
func (c *Client) UploadBatch(ctx context.Context, deviceIdentity string, candidates []*protocol.Candidate, evidence []*protocol.Evidence) error {
	body := map[string]any{
		"candidates": candidates,
		"evidence":   evidence,
	}
	return c.do(ctx, http.MethodPost, "/edge/v1/batches", body, nil, 3)
}

// do runs doOnce with retries on retryable failures.
func (c *Client) do(ctx context.Context, method, path string, body, out any, retries int) error {
	var lastErr error
	for attempt := 0; attempt <= retries; attempt++ {
		if attempt > 0 {
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(backoffDelay(attempt)):
			}
		}
		err := c.doOnce(ctx, method, path, body, out)
		if err == nil {
			return nil
		}
		lastErr = err
		if !isRetryable(err) {
			return err
		}
	}
	return lastErr
}

// doOnce performs a single HTTP round trip with the X-Edge-Version header and
// (when a secret is configured) Bearer authentication.
func (c *Client) doOnce(ctx context.Context, method, path string, body, out any) error {
	urlStr := c.base + path
	var rdr io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("control plane: encode %s %s: %w", method, path, err)
		}
		rdr = bytes.NewReader(data)
	}
	req, err := http.NewRequestWithContext(ctx, method, urlStr, rdr)
	if err != nil {
		return fmt.Errorf("control plane: build %s %s: %w", method, path, err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Edge-Version", c.version)
	req.Header.Set("User-Agent", "siq-edge/"+c.version)
	if c.identity != "" {
		req.Header.Set("X-Edge-Identity", c.identity)
	}
	if c.secret != "" {
		req.Header.Set("Authorization", "Bearer "+c.secret)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return &retryableError{err: fmt.Errorf("control plane %s %s: %w", method, path, err)}
	}
	defer resp.Body.Close()
	limit := int64(1 << 20) // 1 MiB response body cap is plenty for this API
	respBody, err := io.ReadAll(io.LimitReader(resp.Body, limit))
	if err != nil {
		return &retryableError{err: fmt.Errorf("control plane %s %s: read body: %w", method, path, err)}
	}
	snippet := string(bytes.TrimSpace(respBody))
	if len(snippet) > 300 {
		snippet = snippet[:300] + "..."
	}
	if resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500 {
		return &retryableError{err: fmt.Errorf("control plane %s %s: status %d: %s", method, path, resp.StatusCode, snippet)}
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("control plane %s %s: status %d: %s", method, path, resp.StatusCode, snippet)
	}
	if out != nil && len(respBody) > 0 {
		if err := json.Unmarshal(respBody, out); err != nil {
			return fmt.Errorf("control plane: decode %s: %w", path, err)
		}
	}
	return nil
}
