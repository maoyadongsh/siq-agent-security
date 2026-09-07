package receipt

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"time"
)

const maxActionRecords = 8192
const actionWindow = 24 * time.Hour

var ErrActionCapacity = errors.New("action_correlation_capacity")

type CorrelationError struct{ Code string }

func (e *CorrelationError) Error() string { return e.Code }
func correlationError(code string) error  { return &CorrelationError{code} }

type actionRecord struct {
	decision    Receipt
	observation *Receipt
	expires     time.Time
	approved    bool
}

func (e *Engine) actionCapacity(now time.Time) error {
	for id, a := range e.actions {
		if !now.Before(a.expires) {
			delete(e.actions, id)
		}
	}
	if len(e.actions) >= maxActionRecords {
		return ErrActionCapacity
	}
	return nil
}
func str(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}
func (e *Engine) resolveAction(req Request, now time.Time) (*actionRecord, error) {
	var found *actionRecord
	for _, a := range e.actions {
		d := a.decision
		if !now.Before(a.expires) {
			continue
		}
		if req.ActionID != "" && d.ActionID != req.ActionID {
			continue
		}
		if req.DecisionReceiptID != "" && d.ReceiptID != req.DecisionReceiptID {
			continue
		}
		if d.Platform != req.Platform || d.SessionID != req.SessionID || str(d.AgentID) != req.AgentID || d.Tool != req.Tool || str(d.ToolCallID) != req.ToolCallID {
			continue
		}
		if req.ActionID == "" && req.DecisionReceiptID == "" && req.ToolCallID == "" {
			raw, _ := json.Marshal(req.Params)
			h := sha256.Sum256(raw)
			if hex.EncodeToString(h[:]) != d.ParamsDigest {
				continue
			}
		}
		if found != nil {
			return nil, correlationError("observation_ambiguous")
		}
		found = a
	}
	if found == nil {
		return nil, correlationError("observation_decision_missing")
	}
	if (req.ActionID == "") != (req.DecisionReceiptID == "") {
		return nil, correlationError("observation_identity_incomplete")
	}
	if found.decision.Action != ActionAllow && found.decision.Action != ActionRedact && !(found.decision.Action == ActionHold && found.approved) {
		return nil, correlationError("observation_action_not_authorized")
	}
	return found, nil
}

// Observe records one correlated execution result. Retries return the same signed receipt.
func (e *Engine) Observe(req Request, result string) (*Receipt, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	now := e.opts.Now()
	if len(result) > 64<<10 {
		return nil, correlationError("observation_result_too_large")
	}
	a, err := e.resolveAction(req, now)
	if err != nil {
		return nil, err
	}
	digest := sha256.Sum256([]byte(result))
	resultDigest := hex.EncodeToString(digest[:])
	if a.observation != nil {
		if a.observation.ParamsDigest != resultDigest {
			return nil, correlationError("observation_conflict")
		}
		copy := *a.observation
		return &copy, nil
	}
	s, err := e.sessionOrReject(req.SessionID, now)
	if err != nil {
		return nil, err
	}
	labels, rules := e.scanTaints(result)
	for _, label := range labels {
		s.taints[label] = true
	}
	if isEgress(req.Tool, "") || egressTools[req.Tool] {
		s.trifecta.UntrustedInput = true
		s.taints[taintUntrusted] = true
	}
	excerpt := truncate(e.analyzer.Redact(result), excerptMax)
	tf := s.trifecta
	rec := a.decision
	rec.RecordType = "observation"
	rec.DecisionReceiptID = a.decision.ReceiptID
	rec.ReceiptID = a.decision.ReceiptID + "-obs"
	rec.IssuedAt = now.Format(time.RFC3339)
	rec.ParamsDigest = resultDigest
	rec.ParamsExcerpt = &excerpt
	rec.Action = ActionAllow
	rec.Reason = "correlated observation of tool result"
	rec.ReasonCode = "observation_accepted"
	rec.TaintLabels = sortedKeys(s.taints)
	rec.Trifecta = &tf
	rec.MatchedRuleIDs = rules
	rec.Hold = nil
	rec.AdvisoryAction = nil
	rec.DecisionLatencyMS = nil
	if err := e.opts.Chain.Append(&rec); err != nil {
		return nil, err
	}
	a.observation = &rec
	copy := rec
	return &copy, nil
}

// Signed receipts are the recovery authority; caches are never trusted from disk.
func (e *Engine) restoreActionState() error {
	now := e.opts.Now()
	return e.opts.Chain.walkVerified(func(r Receipt) error {
		if r.RecordType == "" {
			return nil
		} // historical v1 records never manufacture action authority
		at, err := time.Parse(time.RFC3339, r.IssuedAt)
		if err != nil {
			return err
		}
		s, err := e.sessionOrReject(r.SessionID, at)
		if err != nil {
			return err
		}
		for _, label := range r.TaintLabels {
			s.taints[label] = true
		}
		if r.Trifecta != nil {
			s.trifecta.PrivateData = s.trifecta.PrivateData || r.Trifecta.PrivateData
			s.trifecta.UntrustedInput = s.trifecta.UntrustedInput || r.Trifecta.UntrustedInput
			s.trifecta.Egress = s.trifecta.Egress || r.Trifecta.Egress
		}
		if r.IntentBinding == "bound" {
			s.boundIntentID = r.IntentID
			s.boundTaskID = r.TaskID
			s.boundIntentDigest = r.IntentDigest
			s.boundAuthorityRevision = r.AuthorityRevision
		}
		if r.TaskSeq > s.taskSeq {
			s.taskSeq = r.TaskSeq
		}
		if r.RecordType == "decision" && (r.Action == ActionAllow || r.Action == ActionRedact) {
			s.parentActionID = r.ActionID
		}
		switch r.RecordType {
		case "decision":
			if !now.Before(at.Add(actionWindow)) {
				return nil
			}
			if len(e.actions) >= maxActionRecords {
				return ErrActionCapacity
			}
			e.actions[r.ActionID] = &actionRecord{decision: r, expires: at.Add(actionWindow)}
		case "observation":
			if a := e.actions[r.ActionID]; a != nil {
				if a.observation != nil && a.observation.ParamsDigest != r.ParamsDigest {
					return correlationError("observation_conflict")
				}
				copy := r
				a.observation = &copy
			}
		case "hold_resolution":
			if r.Action == ActionAllow {
				s.parentActionID = r.ActionID
			}
			if a := e.actions[r.ActionID]; a != nil {
				a.approved = r.Action == ActionAllow
			}
		}
		return nil
	})
}
