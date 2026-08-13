package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

// Task is the control-plane task envelope (task_id/type/scope/payload/
// expires_at/signature). Executed locally by the `tasks` command.
type Task struct {
	TaskID    string          `json:"task_id"`
	Type      string          `json:"type"`
	Scope     json.RawMessage `json:"scope,omitempty"`
	Payload   json.RawMessage `json:"payload,omitempty"`
	ExpiresAt string          `json:"expires_at,omitempty"`
	Signature string          `json:"signature,omitempty"`
}

// ScanRequest is task.payload for type=run-scan tasks.
type ScanRequest struct {
	Connector string          `json:"connector"`
	Scope     json.RawMessage `json:"scope,omitempty"`
}

// VerifyTaskSignature is a Phase-0 TODO. In Phase 1 the control plane will
// sign task envelopes with an Ed25519 key pinned during register; the agent
// must verify task.signature before executing. Until then we log a warning
// and proceed (a signed-task requirement does not exist yet on the wire).
func VerifyTaskSignature(t *Task) error {
	log.Printf("WARNING: task %s signature verification is not implemented yet (Phase 1 TODO); task.signature=%q ignored", t.TaskID, t.Signature)
	return nil
}

// Expired reports whether the task's deadline has passed. An unparseable
// deadline is treated as expired (fail closed).
func (t *Task) Expired(now time.Time) bool {
	if t.ExpiresAt == "" {
		return false
	}
	ts, err := time.Parse(time.RFC3339, t.ExpiresAt)
	if err != nil {
		return true
	}
	return now.After(ts)
}

// Runner executes control-plane tasks on this device.
type Runner struct {
	Client *Client
	State  *State
}

// Execute runs one task and returns the receipt to post to the control plane.
// Errors returned by Execute are infrastructure failures; task-level failures
// are encoded in the receipt (status/error_code) so they can be reported.
func (r *Runner) Execute(ctx context.Context, t *Task) (*Receipt, error) {
	_ = VerifyTaskSignature(t) // Phase-0 TODO: failure must abort execution
	rcpt := &Receipt{
		TaskID:         t.TaskID,
		DeviceIdentity: r.State.DeviceIdentity,
		CompletedAt:    time.Now().UTC().Format(time.RFC3339),
	}
	if t.Expired(time.Now()) {
		rcpt.Status = "failed"
		rcpt.ErrorCode = "expired"
		rcpt.ErrorMessage = "task expired before execution"
		return rcpt, nil
	}
	if t.Type != "run-scan" {
		rcpt.Status = "unsupported"
		rcpt.ErrorMessage = fmt.Sprintf("task type %q is not supported", t.Type)
		return rcpt, nil
	}
	var sr ScanRequest
	if len(t.Payload) > 0 && string(t.Payload) != "null" {
		if err := json.Unmarshal(t.Payload, &sr); err != nil {
			rcpt.Status = "failed"
			rcpt.ErrorCode = "invalid_payload"
			rcpt.ErrorMessage = err.Error()
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
		return rcpt, nil
	}
	out, err := r.runScan(ctx, sr, bin)
	if err != nil {
		rcpt.Status = "failed"
		rcpt.ErrorCode = codeOf(err)
		rcpt.ErrorMessage = err.Error()
		return rcpt, nil
	}
	rcpt.Status = "succeeded"
	rcpt.CandidateCount = len(out.candidates)
	rcpt.EvidenceCount = len(out.evidence)
	rcpt.EvidenceIDs = evidenceIDs(out.evidence)
	rcpt.Cursor = out.cursor
	rcpt.Truncated = out.truncated
	if out.dropped > 0 {
		log.Printf("task %s: dropped %d unreferenced evidence items", t.TaskID, out.dropped)
	}
	return rcpt, nil
}

type scanOutcome struct {
	candidates []*protocol.Candidate
	evidence   []*protocol.Evidence
	dropped    int
	cursor     string
	truncated  bool
}

// runScan drives one connector subprocess through describe → validate_scope
// (when a scope is given) → plan_scan → collect → checkpoint, then seals and
// batch-validates the evidence (contract §5 + hard requirement 4).
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

	// Phase-0 placeholder signer; see evidence.go Signer doc.
	signer, err := NewSigner()
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
		candidates: batch.Candidates,
		evidence:   kept,
		dropped:    len(dropped),
		cursor:     cursor,
		truncated:  batch.Truncated,
	}, nil
}

func evidenceIDs(evs []*protocol.Evidence) []string {
	ids := make([]string, 0, len(evs))
	for _, ev := range evs {
		ids = append(ids, ev.EvidenceID)
	}
	return ids
}
