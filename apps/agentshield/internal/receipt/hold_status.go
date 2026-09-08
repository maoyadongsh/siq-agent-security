package receipt

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"time"
)

// HoldStatusRequest cannot issue or resolve authority. Both server-generated
// references and the complete original call must match before status is read.
type HoldStatusRequest struct {
	Platform          string         `json:"platform"`
	SessionID         string         `json:"session_id"`
	AgentID           string         `json:"agent_id"`
	Tool              string         `json:"tool"`
	ToolCallID        string         `json:"tool_call_id"`
	ActionID          string         `json:"action_id"`
	DecisionReceiptID string         `json:"decision_receipt_id"`
	Params            map[string]any `json:"params"`
}

type HoldStatus struct {
	SchemaVersion     string `json:"schema_version"`
	Status            string `json:"status"`
	ActionID          string `json:"action_id"`
	DecisionReceiptID string `json:"decision_receipt_id"`
	ExpiresAt         string `json:"expires_at"`
	ReasonCode        string `json:"reason_code"`
}

// ReadHoldStatus reads verified action state without appending, granting,
// consuming or extending an approval. It is not a new execution lease.
func (e *Engine) ReadHoldStatus(req HoldStatusRequest) (*HoldStatus, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if req.Platform == "" || req.SessionID == "" || req.AgentID == "" || req.Tool == "" || req.ToolCallID == "" || req.ActionID == "" || req.DecisionReceiptID == "" || req.Params == nil {
		return nil, correlationError("hold_identity_incomplete")
	}
	a := e.actions[req.ActionID]
	if a == nil {
		return nil, correlationError("hold_action_not_found")
	}
	d := a.decision
	raw, err := json.Marshal(req.Params)
	if err != nil {
		return nil, correlationError("hold_identity_mismatch")
	}
	digest := sha256.Sum256(raw)
	if d.ReceiptID != req.DecisionReceiptID || d.Platform != req.Platform || d.SessionID != req.SessionID || str(d.AgentID) != req.AgentID || d.Tool != req.Tool || str(d.ToolCallID) != req.ToolCallID || d.ParamsDigest != hex.EncodeToString(digest[:]) {
		return nil, correlationError("hold_identity_mismatch")
	}
	if d.Action != ActionHold || d.Hold == nil || d.Hold.TimeoutMS <= 0 {
		return nil, correlationError("hold_action_required")
	}
	issued, err := time.Parse(time.RFC3339Nano, d.IssuedAt)
	if err != nil {
		return nil, correlationError("hold_invalid_time")
	}
	expires := issued.Add(time.Duration(d.Hold.TimeoutMS) * time.Millisecond)
	result := &HoldStatus{SchemaVersion: "hold-status/v1", Status: "pending", ActionID: d.ActionID, DecisionReceiptID: d.ReceiptID, ExpiresAt: expires.Format(time.RFC3339Nano), ReasonCode: "hold_pending"}
	now := e.opts.Now()
	switch {
	case !now.Before(expires) || !now.Before(a.expires):
		result.Status, result.ReasonCode = "expired", "hold_expired"
	case a.observation != nil:
		result.Status, result.ReasonCode = "consumed", "hold_consumed"
	case a.holdResolved && !a.approved:
		result.Status, result.ReasonCode = "denied", "hold_denied"
	case a.approved:
		result.Status, result.ReasonCode = "approved", "hold_approved"
	}
	if result.Status == "approved" && !e.holdAuthorityCurrent(req, d, now) {
		result.Status, result.ReasonCode = "denied", "hold_authority_changed"
	}
	return result, nil
}

func (e *Engine) holdAuthorityCurrent(req HoldStatusRequest, d Receipt, now time.Time) bool {
	s := e.sessions[req.SessionID]
	if s == nil || s.boundIntentID != d.IntentID || s.boundTaskID != d.TaskID {
		return false
	}
	r := Request{Platform: req.Platform, SessionID: req.SessionID, AgentID: req.AgentID, Tool: req.Tool, ToolCallID: req.ToolCallID, Params: req.Params}
	r.ContextAssertionID = d.ContextAssertionID
	if e.checkContext(r, d.TaskID, now) != nil {
		return false
	}
	var resolved *IntentContract
	var err error
	if e.opts.IntentLookup != nil {
		resolved, err = e.opts.IntentLookup(req.Platform, req.SessionID, req.AgentID)
	}
	if err != nil {
		return false
	}
	if resolved == nil {
		if d.IntentBinding == "bound" || e.opts.IntentEnforcement == "required" {
			return false
		}
	} else if resolved.IntentID != d.IntentID || resolved.TaskID != d.TaskID || resolved.Digest != d.IntentDigest || resolved.AuthorityRevision != d.AuthorityRevision || resolved.validate(r, now) != nil {
		return false
	}
	var checked Receipt
	descriptor := runtimeaction.Describe(req.Tool, req.Params)
	action, _ := e.evaluate(r, s, descriptor, &checked)
	return (action == ActionAllow || action == ActionHold) && str(checked.MatchedGrantID) == str(d.MatchedGrantID)
}
