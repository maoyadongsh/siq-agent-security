package receipt

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"time"
)

const maxActionRecords = 8192
const actionWindow = 24 * time.Hour

var ErrActionCapacity = errors.New("action_correlation_capacity")

type CorrelationError struct{ Code string }

func (e *CorrelationError) Error() string { return e.Code }
func correlationError(code string) error  { return &CorrelationError{code} }

type actionRecord struct {
	approvedAt     time.Time
	decision       Receipt
	reservation    *Receipt
	reconciliation *Receipt
	observation    *Receipt
	expires        time.Time
	approved       bool
	holdResolved   bool
}

func unresolvedReservation(a *actionRecord) bool {
	return a != nil && a.reservation != nil && a.observation == nil && a.reconciliation == nil
}

func (e *Engine) actionCapacity(now time.Time) error {
	for id, a := range e.actions {
		// A reservation is durable evidence that an external side effect may
		// already have happened. It must remain fail-closed until an observation
		// or explicit reconciliation settles it, even after normal correlation
		// records expire.
		if !now.Before(a.expires) && !unresolvedReservation(a) {
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
		identity := d
		if d.Action == ActionHold && a.reservation != nil {
			identity = *a.reservation
		}
		if !now.Before(a.expires) {
			continue
		}
		if req.ActionID != "" && identity.ActionID != req.ActionID {
			continue
		}
		if req.DecisionReceiptID != "" && identity.ReceiptID != req.DecisionReceiptID {
			continue
		}
		if identity.Platform != req.Platform || identity.SessionID != req.SessionID || str(identity.AgentID) != req.AgentID || identity.Tool != req.Tool || str(identity.ToolCallID) != req.ToolCallID {
			continue
		}
		if req.ActionID == "" && req.DecisionReceiptID == "" && req.ToolCallID == "" {
			raw, _ := json.Marshal(req.Params)
			h := sha256.Sum256(raw)
			if hex.EncodeToString(h[:]) != identity.ParamsDigest {
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
	if found.decision.Action != ActionAllow && found.decision.Action != ActionRedact && !(found.decision.Action == ActionHold && found.approved && found.reservation != nil) {
		return nil, correlationError("observation_action_not_authorized")
	}
	return found, nil
}

// Observe records one correlated execution result. Retries return the same signed receipt.
func (e *Engine) Observe(req Request, result string) (*Receipt, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	if err := intent.ValidateNativeSession(req.Platform, req.SessionID); err != nil {
		return nil, err
	}
	now := e.opts.Now()
	if len(result) > 64<<10 {
		return nil, correlationError("observation_result_too_large")
	}
	a, err := e.resolveAction(req, now)
	if err != nil {
		return nil, err
	}
	if a.reconciliation != nil && a.reconciliation.Action == ActionDeny {
		return nil, correlationError("observation_reconciled_not_occurred")
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
	if runtimeaction.Describe(req.Tool, req.Params).Egress {
		s.trifecta.UntrustedInput = true
		s.taints[taintUntrusted] = true
	}
	excerpt := truncate(e.analyzer.Redact(result), excerptMax)
	tf := s.trifecta
	rec := a.decision
	decisionReceiptID := a.decision.ReceiptID
	if a.decision.Action == ActionHold {
		rec = *a.reservation
		decisionReceiptID = a.reservation.ReceiptID
	}
	rec.RecordType = "observation"
	rec.DecisionReceiptID = decisionReceiptID
	rec.ReceiptID = decisionReceiptID + "-obs"
	rec.IssuedAt = now.Format(time.RFC3339)
	rec.ParamsDigest = resultDigest
	rec.ParamsExcerpt = &excerpt
	rec.Action = ActionAllow
	if rec.EffectiveAction != "" {
		rec.EffectiveAction = ActionAllow
	}
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
	active := map[string]bool{}
	unresolved := map[string]bool{}
	// An unresolved reservation can outlive the normal action correlation
	// window. Determine those action IDs from the verified chain first so the
	// second pass can restore their older decision and approval records.
	if err := e.opts.Chain.walkVerified(func(r Receipt) error {
		if r.RecordType == "" {
			return nil
		}
		switch r.RecordType {
		case "decision":
			at, err := time.Parse(time.RFC3339, r.IssuedAt)
			if err != nil {
				return err
			}
			if now.Before(at.Add(actionWindow)) {
				active[r.ActionID] = true
			}
		case "hold_reservation":
			unresolved[r.ActionID] = true
		case "observation", "hold_reconciliation":
			delete(unresolved, r.ActionID)
		}
		return nil
	}); err != nil {
		return err
	}
	for id := range unresolved {
		active[id] = true
	}
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
		// Late observations/resolutions carry the original task identity. They must
		// not restore its sequence or binding over a more recent trusted decision.
		if r.RecordType == "decision" {
			if r.IntentBinding == "bound" {
				if s.boundIntentID == "" {
					s.taskSeq = 0
					s.parentActionID = ""
				}
				s.boundIntentID, s.boundTaskID = r.IntentID, r.TaskID
				s.boundIntentDigest, s.boundAuthorityRevision = r.IntentDigest, r.AuthorityRevision
				s.boundPrincipal, s.boundProvenanceRefs = r.Principal, r.ProvenanceRefs
			}
			if r.TaskSeq > s.taskSeq {
				s.taskSeq = r.TaskSeq
			}
			if r.Action == ActionAllow || r.Action == ActionRedact {
				s.parentActionID = r.ActionID
			}
		}
		switch r.RecordType {
		case "decision":
			if !active[r.ActionID] {
				return nil
			}
			if len(e.actions) >= maxActionRecords {
				return ErrActionCapacity
			}
			e.actions[r.ActionID] = &actionRecord{decision: r, expires: at.Add(actionWindow)}
		case "observation":
			if a := e.actions[r.ActionID]; a != nil {
				if a.reconciliation != nil && a.reconciliation.Action == ActionDeny {
					return correlationError("observation_reconciled_not_occurred")
				}
				if a.reservation != nil && r.DecisionReceiptID != a.reservation.ReceiptID {
					return correlationError("observation_reservation_mismatch")
				}
				if a.observation != nil && a.observation.ParamsDigest != r.ParamsDigest {
					return correlationError("observation_conflict")
				}
				copy := r
				a.observation = &copy
			}
		case "hold_resolution":
			if r.Action == ActionAllow && r.TaskID == s.boundTaskID && r.IntentID == s.boundIntentID {
				s.parentActionID = r.ActionID
			}
			if a := e.actions[r.ActionID]; a != nil {
				a.approved = r.Action == ActionAllow
				a.approvedAt = at
				a.holdResolved = true
			}
		case "hold_reservation":
			if a := e.actions[r.ActionID]; a != nil {
				deadline, deadlineErr := holdExecutionDeadline(a.decision)
				if a.decision.Action != ActionHold || !a.holdResolved || !a.approved || a.approvedAt.IsZero() ||
					r.DecisionReceiptID != a.decision.ReceiptID || r.Action != ActionAllow || r.ToolCallID == nil ||
					r.Platform != a.decision.Platform || r.SessionID != a.decision.SessionID || str(r.AgentID) != str(a.decision.AgentID) ||
					r.TaskID != a.decision.TaskID || r.Tool != a.decision.Tool || r.ParamsDigest != a.decision.ParamsDigest ||
					at.Before(a.approvedAt) || deadlineErr != nil || !at.Before(deadline) {
					return correlationError("hold_reservation_invalid")
				}
				if a.reservation != nil {
					return correlationError("hold_reservation_conflict")
				}
				copy := r
				a.reservation = &copy
			}
		case "hold_reconciliation":
			if a := e.actions[r.ActionID]; a != nil {
				reservedAt := time.Time{}
				if a.reservation != nil {
					reservedAt, _ = time.Parse(time.RFC3339Nano, a.reservation.IssuedAt)
				}
				if a.reservation == nil || a.observation != nil || r.DecisionReceiptID != a.reservation.ReceiptID ||
					(r.Action != ActionAllow && r.Action != ActionDeny) || r.Platform != a.reservation.Platform ||
					r.SessionID != a.reservation.SessionID || str(r.AgentID) != str(a.reservation.AgentID) ||
					r.TaskID != a.reservation.TaskID || r.Tool != a.reservation.Tool || str(r.ToolCallID) != str(a.reservation.ToolCallID) ||
					r.ParamsDigest != a.reservation.ParamsDigest || reservedAt.IsZero() || at.Before(reservedAt) {
					return correlationError("hold_reconciliation_invalid")
				}
				if a.reconciliation != nil {
					return correlationError("hold_reconciliation_conflict")
				}
				copy := r
				a.reconciliation = &copy
				if r.Action == ActionDeny && s.parentActionID == r.ActionID {
					s.parentActionID = ""
				}
			}
		}
		return nil
	})
}
