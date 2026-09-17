package receipt

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/trustedcontext"
)

// HoldExecutionReserve requests one durable execution reservation after a hold
// was approved. Every field is untrusted and is matched against signed state.
type HoldExecutionReserve struct {
	SchemaVersion      string         `json:"schema_version"`
	Platform           string         `json:"platform"`
	SessionID          string         `json:"session_id"`
	AgentID            string         `json:"agent_id"`
	TaskID             string         `json:"task_id,omitempty"`
	RuntimeTaskID      string         `json:"runtime_task_id,omitempty"`
	Tool               string         `json:"tool"`
	OriginalToolCallID string         `json:"original_tool_call_id"`
	RetryToolCallID    string         `json:"retry_tool_call_id"`
	ActionID           string         `json:"action_id"`
	DecisionReceiptID  string         `json:"decision_receipt_id"`
	Params             map[string]any `json:"params"`
}

type HoldExecutionStatusRequest struct {
	SchemaVersion        string         `json:"schema_version"`
	Platform             string         `json:"platform"`
	SessionID            string         `json:"session_id"`
	AgentID              string         `json:"agent_id"`
	TaskID               string         `json:"task_id,omitempty"`
	RuntimeTaskID        string         `json:"runtime_task_id,omitempty"`
	Tool                 string         `json:"tool"`
	RetryToolCallID      string         `json:"retry_tool_call_id"`
	ActionID             string         `json:"action_id"`
	DecisionReceiptID    string         `json:"decision_receipt_id"`
	ReservationReceiptID string         `json:"reservation_receipt_id"`
	Params               map[string]any `json:"params"`
}

type HoldExecutionStatus struct {
	SchemaVersion           string `json:"schema_version"`
	Status                  string `json:"status"`
	ActionID                string `json:"action_id"`
	DecisionReceiptID       string `json:"decision_receipt_id"`
	ReservationReceiptID    string `json:"reservation_receipt_id"`
	ReconciliationReceiptID string `json:"reconciliation_receipt_id,omitempty"`
	ExpiresAt               string `json:"expires_at"`
	ReasonCode              string `json:"reason_code"`
}

var ErrHoldExecutionInvalid = errors.New("hold_execution_invalid_request")
var ErrHoldExecutionConflict = errors.New("hold_execution_already_reserved")

func paramsDigest(params map[string]any) (string, error) {
	raw, err := json.Marshal(params)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(raw)
	return hex.EncodeToString(digest[:]), nil
}

// pendingReservedExecution prevents a lost reserve response from being turned
// into a fresh hold/approval cycle for the same scoped effect. A completed
// observation releases the guard; expiry requires a new human decision.
func (e *Engine) pendingReservedExecution(req Request, digest string) string {
	for _, a := range e.actions {
		if !unresolvedReservation(a) {
			continue
		}
		d := a.decision
		if d.Platform == req.Platform && d.SessionID == req.SessionID && str(d.AgentID) == req.AgentID && d.Tool == req.Tool && d.ParamsDigest == digest {
			return "hold_execution_uncertain"
		}
	}
	return ""
}

func validateReserveShape(req HoldExecutionReserve) error {
	if req.SchemaVersion != "hold-execution-reserve/v1" || !validExecutionText(req.Platform, 64, false) || !validExecutionText(req.SessionID, 256, false) || !validExecutionText(req.AgentID, 256, false) || !validExecutionText(req.TaskID, 256, true) || !validExecutionText(req.RuntimeTaskID, 256, true) || !validExecutionText(req.Tool, 256, false) || !validExecutionText(req.OriginalToolCallID, 256, false) || !validExecutionText(req.RetryToolCallID, 256, false) || req.OriginalToolCallID == req.RetryToolCallID || !validExecutionText(req.ActionID, 256, false) || !validExecutionText(req.DecisionReceiptID, 256, false) || req.Params == nil {
		return ErrHoldExecutionInvalid
	}
	return nil
}

func validExecutionText(value string, max int, empty bool) bool {
	if (!empty && value == "") || !utf8.ValidString(value) || utf8.RuneCountInString(value) > max || strings.IndexFunc(value, unicode.IsControl) >= 0 {
		return false
	}
	return true
}

func reserveMatchesDecision(req HoldExecutionReserve, d Receipt) bool {
	digest, err := paramsDigest(req.Params)
	return err == nil && d.Action == ActionHold && d.ActionID == req.ActionID && d.ReceiptID == req.DecisionReceiptID && d.Platform == req.Platform && d.SessionID == req.SessionID && str(d.AgentID) == req.AgentID && d.TaskID == req.TaskID && receiptRuntimeTaskID(d) == holdRequestRuntimeTaskID(req.TaskID, req.RuntimeTaskID) && d.Tool == req.Tool && str(d.ToolCallID) == req.OriginalToolCallID && d.ParamsDigest == digest
}

func holdExecutionDeadline(d Receipt) (time.Time, error) {
	if d.Hold == nil || d.Hold.TimeoutMS <= 0 {
		return time.Time{}, ErrHoldExecutionInvalid
	}
	issued, err := time.Parse(time.RFC3339Nano, d.IssuedAt)
	if err != nil {
		return time.Time{}, ErrHoldExecutionInvalid
	}
	deadline := issued.Add(time.Duration(d.Hold.TimeoutMS) * time.Millisecond)
	window := issued.Add(actionWindow)
	if window.Before(deadline) {
		deadline = window
	}
	return deadline, nil
}

// ReserveHoldExecution durably consumes an approved hold before the caller is
// allowed to invoke the external tool. A repeated or concurrent reservation is
// a conflict: response loss is uncertain and must never trigger blind execution.
func (e *Engine) ReserveHoldExecution(req HoldExecutionReserve) (*HoldExecutionStatus, error) {
	if err := validateReserveShape(req); err != nil {
		return nil, err
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	a := e.actions[req.ActionID]
	if a == nil || !reserveMatchesDecision(req, a.decision) {
		return nil, correlationError("hold_identity_mismatch")
	}
	if !a.holdResolved || !a.approved {
		return nil, correlationError("hold_action_not_approved")
	}
	if a.reservation != nil {
		return nil, ErrHoldExecutionConflict
	}
	now := e.opts.Now()
	deadline, err := holdExecutionDeadline(a.decision)
	if err != nil || !now.Before(deadline) {
		return nil, ErrHoldExpired
	}
	statusReq := HoldStatusRequest{Platform: req.Platform, SessionID: req.SessionID, AgentID: req.AgentID, TaskID: req.TaskID, RuntimeTaskID: req.RuntimeTaskID, Tool: req.Tool, ToolCallID: req.OriginalToolCallID, ActionID: req.ActionID, DecisionReceiptID: req.DecisionReceiptID, Params: req.Params}
	if !e.holdAuthorityCurrent(statusReq, a.decision, now) {
		return nil, correlationError("hold_authority_changed")
	}
	reservation := a.decision
	reservation.RecordType = "hold_reservation"
	reservation.ReceiptID = a.decision.ReceiptID + "-exec"
	reservation.DecisionReceiptID = a.decision.ReceiptID
	reservation.IssuedAt = now.Format(time.RFC3339Nano)
	reservation.ToolCallID = &req.RetryToolCallID
	if reservation.SkillAttribution != nil && reservation.SkillAttribution.Status == SkillAttributionVerified {
		binding, bindingErr := trustedcontext.CallBinding(req.Platform, req.SessionID, req.AgentID, holdRequestRuntimeTaskID(req.TaskID, req.RuntimeTaskID), req.Tool, req.RetryToolCallID, req.Params)
		if bindingErr != nil {
			return nil, ErrHoldExecutionInvalid
		}
		attribution := *reservation.SkillAttribution
		attribution.CallBinding = binding
		reservation.SkillAttribution = &attribution
	}
	reservation.Action = ActionAllow
	if reservation.EffectiveAction != "" {
		reservation.EffectiveAction = ActionAllow
	}
	reservation.Reason = "approved hold execution reserved"
	reservation.ReasonCode = "hold_execution_reserved"
	reservation.Hold = nil
	reservation.AdvisoryAction = nil
	reservation.DecisionLatencyMS = nil
	reservation.Hash, reservation.Sig = "", ""
	if err := e.opts.Chain.Append(&reservation); err != nil {
		return nil, err
	}
	a.reservation = &reservation
	return holdExecutionProjection(a, deadline, "reserved", "hold_execution_reserved"), nil
}

func validateExecutionStatusRequest(req HoldExecutionStatusRequest, a *actionRecord) bool {
	if req.SchemaVersion != "hold-execution-status-request/v1" || !validExecutionText(req.Platform, 64, false) || !validExecutionText(req.SessionID, 256, false) || !validExecutionText(req.AgentID, 256, false) || !validExecutionText(req.TaskID, 256, true) || !validExecutionText(req.RuntimeTaskID, 256, true) || !validExecutionText(req.Tool, 256, false) || !validExecutionText(req.RetryToolCallID, 256, false) || !validExecutionText(req.ActionID, 256, false) || !validExecutionText(req.DecisionReceiptID, 256, false) || !validExecutionText(req.ReservationReceiptID, 256, false) || req.Params == nil || a == nil || a.reservation == nil {
		return false
	}
	digest, err := paramsDigest(req.Params)
	r := a.reservation
	d := a.decision
	return err == nil && d.ActionID == req.ActionID && d.ReceiptID == req.DecisionReceiptID && r.ReceiptID == req.ReservationReceiptID && r.Platform == req.Platform && r.SessionID == req.SessionID && str(r.AgentID) == req.AgentID && r.TaskID == req.TaskID && receiptRuntimeTaskID(*r) == holdRequestRuntimeTaskID(req.TaskID, req.RuntimeTaskID) && r.Tool == req.Tool && str(r.ToolCallID) == req.RetryToolCallID && r.ParamsDigest == digest
}

func holdExecutionProjection(a *actionRecord, deadline time.Time, status, reason string) *HoldExecutionStatus {
	out := &HoldExecutionStatus{SchemaVersion: "hold-execution-status/v1", Status: status, ActionID: a.decision.ActionID, DecisionReceiptID: a.decision.ReceiptID, ReservationReceiptID: a.reservation.ReceiptID, ExpiresAt: deadline.Format(time.RFC3339Nano), ReasonCode: reason}
	if a.reconciliation != nil {
		out.ReconciliationReceiptID = a.reconciliation.ReceiptID
	}
	return out
}

// ReadHoldExecutionStatus is read-only. It cannot issue, extend, reserve or
// complete an execution authority.
func (e *Engine) ReadHoldExecutionStatus(req HoldExecutionStatusRequest) (*HoldExecutionStatus, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	a := e.actions[req.ActionID]
	if !validateExecutionStatusRequest(req, a) {
		return nil, correlationError("hold_execution_identity_mismatch")
	}
	deadline, err := holdExecutionDeadline(a.decision)
	if err != nil {
		return nil, err
	}
	now := e.opts.Now()
	if a.observation != nil {
		return holdExecutionProjection(a, deadline, "completed", "hold_execution_completed"), nil
	}
	if a.reconciliation != nil {
		if a.reconciliation.Action == ActionAllow {
			return holdExecutionProjection(a, deadline, "completed", "hold_execution_confirmed_occurred"), nil
		}
		return holdExecutionProjection(a, deadline, "cancelled", "hold_execution_confirmed_not_occurred"), nil
	}
	if a.reservation != nil {
		return holdExecutionProjection(a, deadline, "uncertain", "hold_execution_uncertain"), nil
	}
	if !now.Before(deadline) || !now.Before(a.expires) {
		return holdExecutionProjection(a, deadline, "expired", "hold_expired"), nil
	}
	original := HoldStatusRequest{Platform: a.decision.Platform, SessionID: a.decision.SessionID, AgentID: str(a.decision.AgentID), TaskID: a.decision.TaskID, RuntimeTaskID: a.decision.RuntimeTaskID, Tool: a.decision.Tool, ToolCallID: str(a.decision.ToolCallID), ActionID: a.decision.ActionID, DecisionReceiptID: a.decision.ReceiptID, Params: req.Params}
	if !e.holdAuthorityCurrent(original, a.decision, now) {
		return holdExecutionProjection(a, deadline, "denied", "hold_authority_changed"), nil
	}
	// Only the atomic ReserveHoldExecution response tells its caller to execute.
	// Any later read cannot prove whether that response reached the host or the
	// external side effect started, so it must be uncertain even without a
	// daemon restart.
	return holdExecutionProjection(a, deadline, "uncertain", "hold_execution_uncertain"), nil
}
