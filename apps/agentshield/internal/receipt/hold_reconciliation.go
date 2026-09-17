package receipt

import (
	"errors"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	HoldExecutionOccurred    = "occurred"
	HoldExecutionNotOccurred = "not_occurred"
)

// HoldExecutionReconcile is an administrator's explicit finding after an
// execution reservation entered the uncertain state. It never reuses the old
// reservation or invokes a tool.
type HoldExecutionReconcile struct {
	SchemaVersion        string `json:"schema_version"`
	ActionID             string `json:"action_id"`
	DecisionReceiptID    string `json:"decision_receipt_id"`
	ReservationReceiptID string `json:"reservation_receipt_id"`
	ReservationHash      string `json:"reservation_hash"`
	Outcome              string `json:"outcome"`
	ActorID              string `json:"actor_id"`
}

var ErrHoldReconciliationInvalid = errors.New("hold_reconciliation_invalid_request")
var ErrHoldReconciliationConflict = errors.New("hold_reconciliation_changed_or_resolved")

func validReconciliationActor(value string) bool {
	value = strings.TrimSpace(value)
	return value != "" && utf8.ValidString(value) && utf8.RuneCountInString(value) <= 128 && strings.IndexFunc(value, unicode.IsControl) < 0
}

func validateReconciliationShape(req HoldExecutionReconcile) bool {
	return req.SchemaVersion == "hold-execution-reconcile/v1" &&
		validExecutionText(req.ActionID, 256, false) &&
		validExecutionText(req.DecisionReceiptID, 256, false) &&
		validExecutionText(req.ReservationReceiptID, 256, false) &&
		len(req.ReservationHash) == 64 && isLowerHex(req.ReservationHash) &&
		(req.Outcome == HoldExecutionOccurred || req.Outcome == HoldExecutionNotOccurred) &&
		validReconciliationActor(req.ActorID)
}

func isLowerHex(value string) bool {
	for _, c := range value {
		if (c < '0' || c > '9') && (c < 'a' || c > 'f') {
			return false
		}
	}
	return true
}

// ReconcileHoldExecution closes one uncertain reservation after a human has
// checked the external system. The signed finding is idempotent for the same
// outcome and cannot authorize execution of the old reservation.
func (e *Engine) ReconcileHoldExecution(req HoldExecutionReconcile) (*HoldExecutionStatus, error) {
	if !validateReconciliationShape(req) {
		return nil, ErrHoldReconciliationInvalid
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	a := e.actions[req.ActionID]
	if a == nil || a.decision.ReceiptID != req.DecisionReceiptID || a.reservation == nil ||
		a.reservation.ReceiptID != req.ReservationReceiptID || a.reservation.Hash != req.ReservationHash {
		return nil, ErrHoldReconciliationConflict
	}
	want := ActionDeny
	status, reasonCode := "cancelled", "hold_execution_confirmed_not_occurred"
	if req.Outcome == HoldExecutionOccurred {
		want = ActionAllow
		status, reasonCode = "completed", "hold_execution_confirmed_occurred"
	}
	deadline, err := holdExecutionDeadline(a.decision)
	if err != nil {
		return nil, ErrHoldReconciliationInvalid
	}
	if a.observation != nil {
		return nil, ErrHoldReconciliationConflict
	}
	if a.reconciliation != nil {
		if a.reconciliation.Action != want {
			return nil, ErrHoldReconciliationConflict
		}
		return holdExecutionProjection(a, deadline, status, reasonCode), nil
	}
	now := e.opts.Now()
	rec := *a.reservation
	rec.RecordType = "hold_reconciliation"
	rec.ReceiptID = a.reservation.ReceiptID + "-rec"
	rec.DecisionReceiptID = a.reservation.ReceiptID
	rec.IssuedAt = now.Format(time.RFC3339Nano)
	rec.Action = want
	if rec.EffectiveAction != "" {
		rec.EffectiveAction = want
	}
	rec.ReasonCode = reasonCode
	rec.Reason = "uncertain execution reconciled by " + strings.TrimSpace(req.ActorID)
	rec.Hold = nil
	rec.AdvisoryAction = nil
	rec.DecisionLatencyMS = nil
	rec.Hash, rec.Sig = "", ""
	if err := e.opts.Chain.Append(&rec); err != nil {
		return nil, err
	}
	a.reconciliation = &rec
	if want == ActionDeny {
		if session := e.sessions[a.decision.SessionID]; session != nil && session.parentActionID == a.decision.ActionID {
			session.parentActionID = ""
		}
	}
	return holdExecutionProjection(a, deadline, status, reasonCode), nil
}
