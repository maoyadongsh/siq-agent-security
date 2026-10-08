package server

import (
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/receipt"
)

func TestOpenShellLookupsRejectDuplicateReceiptIdentity(t *testing.T) {
	s, _ := newServer(t, "block")
	session := nativeOpenClawSession(t, "lookup-collision")
	issued := time.Now().UTC().Format(time.RFC3339)
	decision := receipt.Receipt{
		ReceiptID: "legacy-decision", RecordType: "decision", ActionID: "action-one",
		Action: receipt.ActionAllow, Tool: "exec", Platform: "openclaw",
		SessionID: session, IssuedAt: issued,
	}
	if err := s.d.Chain.Append(&decision); err != nil {
		t.Fatal(err)
	}
	decision.ActionID = "action-two"
	if err := s.d.Chain.Append(&decision); err != nil {
		t.Fatal(err)
	}
	_, err := s.validateOpenShellExecutionBinding(openshellSessionExecuteRequest{
		HoldExecutionReserve: receipt.HoldExecutionReserve{
			AgentID: "agent-a", Tool: "exec", DecisionReceiptID: "legacy-decision",
		},
		Target: "agent-a",
	})
	if err == nil || err.Error() != "openshell_receipt_ambiguous" {
		t.Fatalf("session binding selected a duplicate decision: %v", err)
	}
	_, err = s.validateOpenShellTaskExecutionBinding(openshellTaskExecuteRequest{
		HoldExecutionReserve: receipt.HoldExecutionReserve{
			AgentID: "agent-a", Tool: "exec", DecisionReceiptID: "legacy-decision",
			Params: map[string]any{"policy_revision": "rev-1"},
		},
		Target: "agent-a", PolicyRevision: "rev-1",
		NetworkTargets: []string{},
	})
	if err == nil || err.Error() != "openshell_receipt_ambiguous" {
		t.Fatalf("task binding selected a duplicate decision: %v", err)
	}

	reservation := receipt.Receipt{
		ReceiptID: "legacy-reservation", RecordType: openshellTaskReservationRecord,
		ActionID: "reserve-one", TaskID: "task-one", Action: receipt.ActionAllow,
		Tool: "exec", Platform: "openclaw", SessionID: session, IssuedAt: issued,
	}
	if err = s.d.Chain.Append(&reservation); err != nil {
		t.Fatal(err)
	}
	firstHash := reservation.Hash
	reservation.ActionID = "reserve-two"
	reservation.TaskID = "task-two"
	if err = s.d.Chain.Append(&reservation); err != nil {
		t.Fatal(err)
	}
	if got := s.chainReceiptHash("legacy-reservation"); got != "" {
		t.Fatalf("ambiguous reservation hash selected %s; first was %s", got, firstHash)
	}
	facts, code := s.taskChainFacts("legacy-reservation")
	if facts != nil || code != "openshell_receipt_ambiguous" {
		task := ""
		if facts != nil {
			task = facts.TaskID
		}
		t.Fatalf("task lookup selected %q with code %s", task, code)
	}
}

func TestOpenShellLookupsKeepUniqueReceiptIdentity(t *testing.T) {
	s, _ := newServer(t, "block")
	session := nativeOpenClawSession(t, "lookup-unique")
	decision := receipt.Receipt{
		ReceiptID: "unique-decision", RecordType: "decision", ActionID: "only-action",
		Action: receipt.ActionAllow, Tool: "exec", Platform: "openclaw",
		SessionID: session, IssuedAt: time.Now().UTC().Format(time.RFC3339),
	}
	if err := s.d.Chain.Append(&decision); err != nil {
		t.Fatal(err)
	}
	_, err := s.validateOpenShellExecutionBinding(openshellSessionExecuteRequest{
		HoldExecutionReserve: receipt.HoldExecutionReserve{
			AgentID: "agent-a", Tool: "exec", DecisionReceiptID: "unique-decision",
		},
		Target: "agent-a",
	})
	if err == nil || err.Error() != "openshell_decision_missing" {
		t.Fatalf("unique decision without a grant changed classification: %v", err)
	}
	reservation := receipt.Receipt{
		ReceiptID: "unique-reservation", RecordType: openshellTaskReservationRecord,
		ActionID: "only-reserve", TaskID: "task-only", Action: receipt.ActionAllow,
		Tool: "exec", Platform: "openclaw", SessionID: session,
		IssuedAt: time.Now().UTC().Format(time.RFC3339),
	}
	if err = s.d.Chain.Append(&reservation); err != nil {
		t.Fatal(err)
	}
	if got := s.chainReceiptHash("unique-reservation"); got != reservation.Hash {
		t.Fatalf("unique hash = %s, want %s", got, reservation.Hash)
	}
	facts, code := s.taskChainFacts("unique-reservation")
	if code != "" || facts == nil || facts.TaskID != "task-only" || facts.Reconciliation != nil {
		t.Fatalf("unique reservation lost: code=%s facts=%v", code, facts)
	}
	only := reservation
	only.RecordType = openshellTaskReconcileRecord
	only.ReceiptID = "unique-reservation-rec"
	only.DecisionReceiptID = "unique-reservation"
	only.Action = receipt.ActionDeny
	if err = s.d.Chain.Append(&only); err != nil {
		t.Fatal(err)
	}
	facts, code = s.taskChainFacts("unique-reservation")
	if code != "" || facts == nil || facts.Reconciliation == nil || facts.Reconciliation.Action != receipt.ActionDeny {
		t.Fatalf("single reconciliation lost: code=%s facts=%v", code, facts)
	}
}

func TestTaskChainFactsRejectsContradictoryClosure(t *testing.T) {
	s, _ := newServer(t, "block")
	session := nativeOpenClawSession(t, "closure-collision")
	issued := time.Now().UTC().Format(time.RFC3339)
	reservation := receipt.Receipt{
		ReceiptID: "legacy-reservation", RecordType: openshellTaskReservationRecord,
		ActionID: "reserve-one", TaskID: "task-one", Action: receipt.ActionAllow,
		Tool: "exec", Platform: "openclaw", SessionID: session, IssuedAt: issued,
	}
	if err := s.d.Chain.Append(&reservation); err != nil {
		t.Fatal(err)
	}
	notOccurred := reservation
	notOccurred.RecordType = openshellTaskReconcileRecord
	notOccurred.ReceiptID = "legacy-reservation-rec"
	notOccurred.DecisionReceiptID = reservation.ReceiptID
	notOccurred.Action = receipt.ActionDeny
	if err := s.d.Chain.Append(&notOccurred); err != nil {
		t.Fatal(err)
	}
	occurred := notOccurred
	occurred.ReceiptID = "legacy-reservation-rec-later"
	occurred.Action = receipt.ActionAllow
	if err := s.d.Chain.Append(&occurred); err != nil {
		t.Fatal(err)
	}
	facts, code := s.taskChainFacts(reservation.ReceiptID)
	if facts != nil || code != "openshell_receipt_ambiguous" {
		action := ""
		if facts != nil && facts.Reconciliation != nil {
			action = string(facts.Reconciliation.Action)
		}
		t.Fatalf("contradictory reconciliation selected %q, code %s", action, code)
	}

	s, _ = newServer(t, "block")
	reservation.SessionID = nativeOpenClawSession(t, "observation-collision")
	if err := s.d.Chain.Append(&reservation); err != nil {
		t.Fatal(err)
	}
	firstObs := reservation
	firstObs.RecordType = "observation"
	firstObs.ReceiptID = reservation.ReceiptID + "-obs"
	firstObs.DecisionReceiptID = reservation.ReceiptID
	firstObs.ParamsDigest = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	if err := s.d.Chain.Append(&firstObs); err != nil {
		t.Fatal(err)
	}
	secondObs := firstObs
	secondObs.ParamsDigest = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	if err := s.d.Chain.Append(&secondObs); err != nil {
		t.Fatal(err)
	}
	facts, code = s.taskChainFacts(reservation.ReceiptID)
	if facts != nil || code != "openshell_receipt_ambiguous" {
		digest := ""
		if facts != nil && facts.Observation != nil {
			digest = facts.Observation.ParamsDigest
		}
		t.Fatalf("contradictory observation selected %s, code %s", digest, code)
	}
}
