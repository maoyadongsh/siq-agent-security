package main

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"strings"
	"time"

	"siq-agent-security/edge/agent/canon"
	"siq-agent-security/edge/agent/protocol"
)

// Task is the control-plane task envelope (task_id/task_type/payload/
// environment_id/expires_at/signature). Executed locally by the `tasks` command.
type Task struct {
	TaskID        string          `json:"id"` // 控制面契约字段名为 id（签名信封内仍为 task_id）
	TaskType      string          `json:"task_type"`
	EnvironmentID string          `json:"environment_id,omitempty"`
	Payload       json.RawMessage `json:"payload,omitempty"`
	ExpiresAt     string          `json:"expires_at,omitempty"`
	Signature     string          `json:"signature,omitempty"`
}

// ScanRequest is task.payload for type=run-scan tasks.
type ScanRequest struct {
	Connector string          `json:"connector"`
	Scope     json.RawMessage `json:"scope,omitempty"`
}

// VerifyTaskSignature verifies the control-plane Ed25519 signature over the
// canonical task envelope {task_id, task_type, environment_id, payload,
// expires_at}. Canonicalization matches apps/control-api/app/signing.py:
// json.dumps(..., sort_keys=True, separators=(",", ":")) — CPython default
// ensure_ascii=True (not evidence_signing.canonical_json). Payload numbers are
// decoded with json.Number so 100 vs 100.0 survive. Fail closed (threat T5).
func VerifyTaskSignature(t *Task, controlPlanePublicKeyB64 string) error {
	if t.Signature == "" {
		return errors.New("task signature missing; refusing unsigned task (fail closed)")
	}
	if controlPlanePublicKeyB64 == "" {
		return errors.New("control-plane public key not pinned in state; re-run register")
	}
	pubRaw, err := base64.StdEncoding.DecodeString(controlPlanePublicKeyB64)
	if err != nil || len(pubRaw) != ed25519.PublicKeySize {
		return fmt.Errorf("invalid pinned control-plane public key: %w", err)
	}
	var payload any
	if len(t.Payload) > 0 && string(t.Payload) != "null" {
		payload, err = canon.Decode(t.Payload)
		if err != nil {
			return fmt.Errorf("task payload is not valid JSON: %w", err)
		}
	} else {
		payload = map[string]any{}
	}
	envelope := map[string]any{
		"task_id":        t.TaskID,
		"task_type":      t.TaskType,
		"environment_id": t.EnvironmentID,
		"payload":        payload,
		"expires_at":     t.ExpiresAt,
	}
	canonical, err := canon.Marshal(envelope)
	if err != nil {
		return fmt.Errorf("task envelope canonicalization failed: %w", err)
	}
	sig, err := base64.StdEncoding.DecodeString(t.Signature)
	if err != nil {
		return fmt.Errorf("task signature is not valid base64: %w", err)
	}
	if !ed25519.Verify(ed25519.PublicKey(pubRaw), canonical, sig) {
		return errors.New("task signature verification failed; task rejected")
	}
	return nil
}

// TaskExpiryLeeway is the allowed clock skew when comparing now to expires_at
// (DEV10 / M-E5). Local clocks slightly ahead of the control plane still accept
// the task until expires_at+leeway; missing/unparseable deadlines never get a
// grace window.
const TaskExpiryLeeway = 60 * time.Second

// Expired reports whether the task must not execute.
//
// Fail-closed rules (DEV10):
//   - empty expires_at → expired (no unlimited legacy validity);
//   - unparseable expires_at → expired;
//   - now after expires_at+TaskExpiryLeeway → expired.
func (t *Task) Expired(now time.Time) bool {
	return t.ExpiryError(now) != nil
}

// ExpiryError returns a stable reason when the task is past its deadline, or
// nil when execution is still allowed under TaskExpiryLeeway.
func (t *Task) ExpiryError(now time.Time) error {
	if strings.TrimSpace(t.ExpiresAt) == "" {
		return errors.New("task expires_at missing; refusing task without deadline (fail closed)")
	}
	ts, err := parseTaskTime(t.ExpiresAt)
	if err != nil {
		return fmt.Errorf("task expires_at unparseable; refusing task (fail closed): %w", err)
	}
	deadline := ts.Add(TaskExpiryLeeway)
	if now.After(deadline) {
		return fmt.Errorf("task expired at %s (leeway %s)", ts.UTC().Format(time.RFC3339), TaskExpiryLeeway)
	}
	return nil
}

func parseTaskTime(s string) (time.Time, error) {
	ts, err := time.Parse(time.RFC3339, s)
	if err == nil {
		return ts, nil
	}
	// Control plane may emit naive UTC (no zone suffix); interpret as UTC.
	ts, err = time.Parse("2006-01-02T15:04:05.999999", s)
	if err != nil {
		return time.Time{}, err
	}
	return ts.UTC(), nil
}

// Runner executes control-plane tasks on this device.
type Runner struct {
	Client *Client
	State  *State
}

// Execute runs one task and returns the receipt to post to the control plane.
// Errors returned by Execute are infrastructure failures; task-level failures
// are encoded in the receipt (status/error_code) so they can be reported.
//
// DEV10 / M-E5: after signature and expiry checks, a prior local outcome with
// the same content digest is reused (no connector re-run). A prior outcome
// with a different digest fails closed as task_content_conflict.
func (r *Runner) Execute(ctx context.Context, t *Task) (*Receipt, error) {
	rcpt := &Receipt{
		TaskID:         t.TaskID,
		DeviceIdentity: r.State.DeviceIdentity,
		CompletedAt:    time.Now().UTC().Format(time.RFC3339),
	}
	if err := VerifyTaskSignature(t, r.State.ControlPlanePublicKey); err != nil {
		rcpt.Status = "failed"
		rcpt.ErrorCode = "signature_invalid"
		rcpt.ErrorMessage = err.Error()
		return rcpt, nil
	}
	if err := t.ExpiryError(time.Now()); err != nil {
		rcpt.Status = "failed"
		rcpt.ErrorCode = "expired"
		rcpt.ErrorMessage = err.Error()
		return rcpt, nil
	}
	if reused, err := LookupExecReuse(t); err != nil {
		rcpt.Status = "failed"
		rcpt.ErrorCode = "task_content_conflict"
		rcpt.ErrorMessage = err.Error()
		return rcpt, nil
	} else if reused != nil {
		reused.DeviceIdentity = r.State.DeviceIdentity
		reused.CompletedAt = time.Now().UTC().Format(time.RFC3339)
		log.Printf("task %s: reusing prior local outcome (content digest match)", t.TaskID)
		return reused, nil
	}
	if t.TaskType != "scan" {
		rcpt.Status = "failed" // 控制面回执枚举仅 success|failed
		rcpt.ErrorCode = "unsupported_task_type"
		rcpt.ErrorMessage = fmt.Sprintf("task type %q is not supported", t.TaskType)
		_ = SaveExecLedgerRecord(t, rcpt)
		return rcpt, nil
	}
	var sr ScanRequest
	if len(t.Payload) > 0 && string(t.Payload) != "null" {
		if err := json.Unmarshal(t.Payload, &sr); err != nil {
			rcpt.Status = "failed"
			rcpt.ErrorCode = "invalid_payload"
			rcpt.ErrorMessage = err.Error()
			_ = SaveExecLedgerRecord(t, rcpt)
			return rcpt, nil
		}
	}
	if sr.Connector == "" {
		sr.Connector = "hermes"
	}
	bin, err := ResolveConnectorBin(sr.Connector, "")
	if err != nil {
		rcpt.Status = "failed"
		rcpt.ErrorCode = protocol.CodeUnsupported
		rcpt.ErrorMessage = err.Error()
		_ = SaveExecLedgerRecord(t, rcpt)
		return rcpt, nil
	}
	out, err := r.runScan(ctx, sr, bin)
	if err != nil {
		rcpt.Status = "failed"
		rcpt.ErrorCode = codeOf(err)
		rcpt.ErrorMessage = err.Error()
		_ = SaveExecLedgerRecord(t, rcpt)
		return rcpt, nil
	}
	rcpt.Status = "success"
	rcpt.CandidateCount = len(out.candidates)
	rcpt.EvidenceCount = len(out.evidence)
	rcpt.EvidenceIDs = evidenceIDs(out.evidence)
	rcpt.Cursor = out.cursor
	rcpt.Truncated = out.truncated
	if out.dropped > 0 {
		log.Printf("task %s: dropped %d unreferenced evidence items", t.TaskID, out.dropped)
	}
	if len(out.candidates) == 0 && len(out.evidence) == 0 && len(out.permissions) == 0 {
		// 空批是正常结果（如无标签容器）：跳过上传，回执记录 0 发现
		if err := SavePendingReceipt(rcpt); err != nil {
			log.Printf("task %s: pending receipt journal failed: %v", t.TaskID, err)
		}
		_ = SaveExecLedgerRecord(t, rcpt)
		return rcpt, nil
	}
	signer, err := loadSigner(r.State)
	if err != nil {
		rcpt.Status = "failed"
		rcpt.ErrorCode = "signer_unavailable"
		rcpt.ErrorMessage = err.Error()
		_ = SaveExecLedgerRecord(t, rcpt)
		return rcpt, nil
	}
	if err := r.Client.UploadBatch(ctx, t.TaskID, out.candidates, out.evidence, out.permissions, signer); err != nil {
		rcpt.Status = "failed"
		rcpt.ErrorCode = "batch_upload_failed"
		rcpt.ErrorMessage = err.Error()
		_ = SaveExecLedgerRecord(t, rcpt)
		return rcpt, nil
	}
	// R04：上传成功后、回执提交前落盘，崩溃后可 DrainPendingReceipts 恢复。
	if err := SavePendingReceipt(rcpt); err != nil {
		log.Printf("task %s: pending receipt journal failed: %v", t.TaskID, err)
	}
	_ = SaveExecLedgerRecord(t, rcpt)
	return rcpt, nil
}

type scanOutcome struct {
	candidates  []*protocol.Candidate
	evidence    []*protocol.Evidence
	permissions []*protocol.PermissionFact
	dropped     int
	cursor      string
	truncated   bool
}

// runScan drives one connector subprocess through describe → validate_scope
// (when a scope is given) → plan_scan → collect → checkpoint, then seals and
// batch-validates the evidence (contract §5 + hard requirement 4).
// loadSigner restores the device signing key from state (persisted since
// register); falls back to generating a fresh one and persisting it.
func loadSigner(state *State) (*Signer, error) {
	if state.SignerSeed != "" {
		return NewSignerFromSeed(state.SignerSeed)
	}
	signer, err := NewSigner()
	if err != nil {
		return nil, err
	}
	state.SignerSeed = signer.SeedB64()
	if err := state.Save(); err != nil {
		return nil, fmt.Errorf("signer: persist seed: %w", err)
	}
	return signer, nil
}

func (r *Runner) runScan(ctx context.Context, sr ScanRequest, bin string) (*scanOutcome, error) {
	cc, err := NewSubprocessConnector(ctx, bin, SubprocessOptions{Name: sr.Connector, Version: agentVersion})
	if err != nil {
		return nil, err
	}
	defer cc.Close()

	caps, err := cc.Describe(ctx)
	if err != nil {
		return nil, err
	}
	log.Printf("connector %s: version=%s objects=%v network_access=%v", sr.Connector, caps.Version, caps.Objects, caps.NetworkAccess)

	var scope *protocol.Scope
	if len(sr.Scope) > 0 && string(sr.Scope) != "null" {
		if err := json.Unmarshal(sr.Scope, &scope); err != nil {
			return nil, fmt.Errorf("task scope is not a valid Scope object: %w", err)
		}
		vr, err := cc.ValidateScope(ctx, scope)
		if err != nil {
			return nil, err
		}
		if !vr.Valid {
			return nil, fmt.Errorf("%w: %s", ErrScopeInvalid, strings.Join(vr.Errors, "; "))
		}
	}
	plan, err := cc.PlanScan(ctx, scope, "")
	if err != nil {
		return nil, err
	}
	batch, err := cc.Collect(ctx, plan)
	if err != nil {
		return nil, err
	}
	cursor, err := cc.Checkpoint(ctx)
	if err != nil {
		return nil, err
	}

	signer, err := loadSigner(r.State)
	if err != nil {
		return nil, err
	}
	for _, ev := range batch.Evidence {
		if err := SealEvidence(ev, signer, r.State.DeviceIdentity); err != nil {
			return nil, err
		}
	}
	kept, dropped, err := ValidateBatchReferences(batch.Candidates, batch.Evidence)
	if err != nil {
		return nil, err
	}
	return &scanOutcome{
		candidates:  batch.Candidates,
		evidence:    kept,
		permissions: batch.PermissionFacts,
		dropped:     len(dropped),
		cursor:      cursor,
		truncated:   batch.Truncated,
	}, nil
}

func evidenceIDs(evs []*protocol.Evidence) []string {
	ids := make([]string, 0, len(evs))
	for _, ev := range evs {
		ids = append(ids, ev.EvidenceID)
	}
	return ids
}
