package receipt

import (
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

// HistoricalEffectActions verifies one complete ledger pass and retains only
// requested decisions. It never makes expired actions executable again.
func (e *Engine) HistoricalEffectActions(records []effectevidence.Record) (func(string, string) (effectevidence.Action, error), error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if len(records) > maxActionRecords {
		return nil, ErrActionCapacity
	}
	type pair struct{ action, receipt string }
	wanted := map[pair]bool{}
	found := map[pair]Receipt{}
	approved := map[pair]bool{}
	approvedAt := map[pair]time.Time{}
	resolved := map[pair]bool{}
	for _, record := range records {
		r := record.Evidence
		if r.ActionID == "" || r.DecisionReceiptID == "" {
			return nil, effectevidence.ErrCorrelation
		}
		wanted[pair{r.ActionID, r.DecisionReceiptID}] = true
	}
	lastSeq, lastHash := -1, GenesisPrev
	err := e.opts.Chain.walkVerified(func(r Receipt) error {
		lastSeq, lastHash = r.Seq, r.Hash
		if r.RecordType == "decision" {
			p := pair{r.ActionID, r.ReceiptID}
			if !wanted[p] {
				return nil
			}
			if _, exists := found[p]; exists {
				return effectevidence.ErrCorrelation
			}
			found[p] = r
		}
		if r.RecordType == "hold_resolution" {
			p := pair{r.ActionID, r.DecisionReceiptID}
			if !wanted[p] {
				return nil
			}
			d, exists := found[p]
			if !exists || resolved[p] || d.Action != ActionHold || d.TaskID != r.TaskID || d.IntentID != r.IntentID || d.IntentDigest != r.IntentDigest || d.Platform != r.Platform || d.SessionID != r.SessionID || str(d.AgentID) != str(r.AgentID) || (r.Action != ActionAllow && r.Action != ActionDeny) {
				return effectevidence.ErrCorrelation
			}
			resolved[p] = true
			approved[p] = r.Action == ActionAllow
			at, err := time.Parse(time.RFC3339Nano, r.IssuedAt)
			if err != nil {
				return effectevidence.ErrCorrelation
			}
			approvedAt[p] = at
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	if lastSeq != e.opts.Chain.seq || lastHash != e.opts.Chain.head {
		return nil, effectevidence.ErrCorrelation
	}
	out := map[pair]effectevidence.Action{}
	for p := range wanted {
		d, exists := found[p]
		if !exists {
			return nil, effectevidence.ErrCorrelation
		}
		at, err := time.Parse(time.RFC3339, d.IssuedAt)
		if err != nil {
			return nil, effectevidence.ErrCorrelation
		}
		authorizedAt := at
		if d.Action == ActionHold {
			authorizedAt = approvedAt[p]
		}
		out[p] = effectevidence.Action{AuthorizedAt: authorizedAt, ActionID: d.ActionID, DecisionReceiptID: d.ReceiptID, TaskID: d.TaskID, IntentID: d.IntentID, IntentDigest: d.IntentDigest, Platform: d.Platform, SessionID: d.SessionID, AgentID: str(d.AgentID), IssuedAt: at, Authorized: d.Action == ActionAllow || d.Action == ActionRedact || d.Action == ActionHold && approved[p], Effects: append([]string(nil), d.Effects...), Resources: append([]runtimeaction.ResourceRef(nil), d.ResourceRefs...)}
	}
	return func(actionID, receiptID string) (effectevidence.Action, error) {
		a, ok := out[pair{actionID, receiptID}]
		if !ok {
			return effectevidence.Action{}, effectevidence.ErrCorrelation
		}
		a.Effects = append([]string(nil), a.Effects...)
		a.Resources = append([]runtimeaction.ResourceRef(nil), a.Resources...)
		return a, nil
	}, nil
}
