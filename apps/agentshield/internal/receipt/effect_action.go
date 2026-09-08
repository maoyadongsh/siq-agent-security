package receipt

import (
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

// EffectAction reads authoritative action state, including denied decisions so
// an independent observer can report unauthorized effects. It grants no right
// to execute. The caller must separately authenticate the effect observer.
func (e *Engine) EffectAction(actionID, receiptID string) (effectevidence.Action, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if actionID == "" || receiptID == "" {
		return effectevidence.Action{}, effectevidence.ErrCorrelation
	}
	for _, a := range e.actions {
		d := a.decision
		if d.ActionID != actionID || d.ReceiptID != receiptID || !e.opts.Now().Before(a.expires) {
			continue
		}
		at, err := time.Parse(time.RFC3339, d.IssuedAt)
		if err != nil {
			return effectevidence.Action{}, effectevidence.ErrCorrelation
		}
		return effectevidence.Action{ActionID: d.ActionID, DecisionReceiptID: d.ReceiptID, TaskID: d.TaskID, Platform: d.Platform, SessionID: d.SessionID, AgentID: str(d.AgentID), IssuedAt: at,
			Authorized: d.Action == ActionAllow || d.Action == ActionRedact || (d.Action == ActionHold && a.approved),
			Effects:    append([]string(nil), d.Effects...), Resources: append([]runtimeaction.ResourceRef(nil), d.ResourceRefs...)}, nil
	}
	return effectevidence.Action{}, effectevidence.ErrCorrelation
}
