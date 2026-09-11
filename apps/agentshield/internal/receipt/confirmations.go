package receipt

import (
	"errors"
	"sort"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/grant"
)

// Confirmation is a read-only projection, not a lease to execute a tool.
// Excerpt is copied from the existing redacted receipt; raw parameters never enter it.
type Confirmation struct {
	ActionID          string  `json:"action_id"`
	DecisionReceiptID string  `json:"decision_receipt_id"`
	DecisionHash      string  `json:"decision_hash"`
	ParamsDigest      string  `json:"params_digest"`
	Platform          string  `json:"platform"`
	AgentID           string  `json:"agent_id"`
	SessionID         string  `json:"session_id"`
	Tool              string  `json:"tool"`
	ToolCallID        string  `json:"tool_call_id"`
	GrantID           string  `json:"grant_id"`
	IssuedAt          string  `json:"issued_at"`
	ExpiresAt         *string `json:"expires_at"`
	Status            string  `json:"status"`
	ParamsExcerpt     *string `json:"params_excerpt"`
}
type ConfirmationList struct {
	SchemaVersion string         `json:"schema_version"`
	Items         []Confirmation `json:"items"`
}
type ConfirmationResolve struct {
	SchemaVersion     string `json:"schema_version"`
	DecisionReceiptID string `json:"decision_receipt_id"`
	DecisionHash      string `json:"decision_hash"`
	ParamsDigest      string `json:"params_digest"`
	Approve           bool   `json:"approve"`
	ActorID           string `json:"actor_id"`
}

var ErrConfirmationInvalid = errors.New("confirmation_invalid_request")
var ErrConfirmationConflict = errors.New("confirmation_changed_or_resolved")

func (e *Engine) Confirmations() ConfirmationList {
	e.mu.Lock()
	defer e.mu.Unlock()
	now := e.opts.Now()
	actions := make([]*actionRecord, 0)
	for _, a := range e.actions {
		if a.decision.Action == ActionHold && now.Before(a.expires) {
			actions = append(actions, a)
		}
	}
	sort.Slice(actions, func(i, j int) bool { return actions[i].decision.Seq > actions[j].decision.Seq })
	out := ConfirmationList{SchemaVersion: "local-confirmations/v1", Items: make([]Confirmation, 0, len(actions))}
	for _, a := range actions {
		out.Items = append(out.Items, e.confirmationLocked(a, now))
	}
	return out
}
func (e *Engine) confirmationLocked(a *actionRecord, now time.Time) Confirmation {
	d := a.decision
	c := Confirmation{ActionID: d.ActionID, DecisionReceiptID: d.ReceiptID, DecisionHash: d.Hash, ParamsDigest: d.ParamsDigest,
		Platform: d.Platform, AgentID: str(d.AgentID), SessionID: d.SessionID, Tool: d.Tool, ToolCallID: str(d.ToolCallID),
		GrantID: str(d.MatchedGrantID), IssuedAt: d.IssuedAt, Status: "pending"}
	if d.ParamsExcerpt != nil {
		value := truncate(*d.ParamsExcerpt, excerptMax)
		c.ParamsExcerpt = &value
	}
	at, err := time.Parse(time.RFC3339Nano, d.IssuedAt)
	if err != nil || d.Hold == nil || d.Hold.TimeoutMS <= 0 {
		c.Status = "unavailable"
		return c
	}
	deadline := at.Add(time.Duration(d.Hold.TimeoutMS) * time.Millisecond)
	value := deadline.Format(time.RFC3339Nano)
	c.ExpiresAt = &value
	switch {
	case !now.Before(deadline) || !now.Before(a.expires):
		c.Status = "expired"
	case a.observation != nil:
		c.Status = "consumed"
	case a.holdResolved && !a.approved:
		c.Status = "denied"
	case !e.confirmationAuthorityCurrent(d, now):
		c.Status = "unavailable"
	case a.holdResolved:
		c.Status = "approved"
	}
	return c
}

// This checks current identity and lifetime without attempting to reconstruct
// parameters from an excerpt. Full policy/provenance checks remain in hold-status.
func (e *Engine) confirmationAuthorityCurrent(d Receipt, now time.Time) bool {
	session := e.sessions[d.SessionID]
	if session == nil || session.boundIntentID != d.IntentID || session.boundTaskID != d.TaskID || (d.IntentBinding != "bound" && e.opts.IntentEnforcement == "required") {
		return false
	}
	var g *grant.Grant
	if d.IntentBinding == "bound" {
		if e.opts.IntentLookup == nil {
			return false
		}
		current, err := e.opts.IntentLookup(d.Platform, d.SessionID, str(d.AgentID))
		if err != nil || current == nil || current.IntentID != d.IntentID || current.TaskID != d.TaskID || current.Digest != d.IntentDigest || current.AuthorityRevision != d.AuthorityRevision {
			return false
		}
		g = current.SelectedGrant
	}
	if g == nil && e.opts.Grants != nil {
		g = e.opts.Grants(d.Platform, str(d.AgentID))
	}
	return g != nil && g.GrantID == str(d.MatchedGrantID) && (g.Status == "deployed" || g.Status == "effective") && grant.ValidateLifetime(*g, now) == nil
}

// ResolveConfirmation binds a single human click to the displayed immutable
// decision and refuses all replays, including simultaneous identical approvals.
func (e *Engine) ResolveConfirmation(actionID string, req ConfirmationResolve) (*Receipt, error) {
	actor := strings.TrimSpace(req.ActorID)
	if req.SchemaVersion != "local-confirmation-resolve/v1" || actor == "" || !utf8.ValidString(actor) || utf8.RuneCountInString(actor) > 128 || strings.IndexFunc(actor, unicode.IsControl) >= 0 {
		return nil, ErrConfirmationInvalid
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	a := e.actions[actionID]
	if a == nil || a.decision.Action != ActionHold {
		return nil, ErrConfirmationConflict
	}
	d := a.decision
	if d.ReceiptID != req.DecisionReceiptID || d.Hash != req.DecisionHash || d.ParamsDigest != req.ParamsDigest || a.holdResolved || e.confirmationLocked(a, e.opts.Now()).Status != "pending" {
		return nil, ErrConfirmationConflict
	}
	return e.resolveHoldLocked(d, req.Approve, actor)
}
