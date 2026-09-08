package effectevidence

import (
	"errors"
	"time"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

// Action is a transient projection of the verified decision ledger. Only the
// engine may supply it; it must never be decoded from an evidence request.
type Action struct {
	AuthorizedAt                        time.Time
	IntentID, IntentDigest              string
	ActionID, DecisionReceiptID, TaskID string
	Platform, SessionID, AgentID        string
	IssuedAt                            time.Time
	Authorized                          bool
	Effects                             []string
	Resources                           []runtimeaction.ResourceRef
}

var (
	ErrCorrelation = errors.New("effect_evidence_action_mismatch")
	ErrObserver    = errors.New("effect_evidence_observer_mismatch")
)

// Correlate checks the trusted action and provisioned observer, then classifies
// scope violations. It returns an unsigned record and an incident code for the
// storage layer to commit together. It does not accept caller-supplied authority.
func Correlate(e Evidence, action Action, observer Source, now time.Time) (Evidence, string, error) {
	if err := e.Validate(now); err != nil {
		return Evidence{}, "", err
	}
	if e.Source != observer {
		return Evidence{}, "", ErrObserver
	}
	if action.ActionID == "" || action.DecisionReceiptID == "" || e.ActionID != action.ActionID || e.DecisionReceiptID != action.DecisionReceiptID || action.IssuedAt.IsZero() {
		return Evidence{}, "", ErrCorrelation
	}
	observed, _ := time.Parse(time.RFC3339Nano, e.ObservedAt)
	if observed.Before(action.IssuedAt) {
		return Evidence{}, "", ErrCorrelation
	}
	e.Signature = ""
	independent := member(e.Source.Independence, "host_independent", "external_independent")
	if !independent {
		return e, "", nil
	}
	if e.ExecutionState == "completed" && (!action.Authorized || (!action.AuthorizedAt.IsZero() && observed.Before(action.AuthorizedAt))) {
		e.Result = "unexpected"
		return e, "unauthorized_effect_observed", nil
	}
	matched := false
	for _, ref := range action.Resources {
		value, err := ResourceReference(ref)
		if err == nil && value == e.ResourceRef {
			matched = true
			break
		}
	}
	if !member(e.EffectType, action.Effects...) || !matched {
		if e.ExecutionState == "completed" {
			e.Result = "unexpected"
			return e, "effect_scope_mismatch", nil
		}
		e.Result = "unknown"
	}
	return e, "", nil
}
