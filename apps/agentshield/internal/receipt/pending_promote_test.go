package receipt

import (
	"testing"

	"siq-agent-security/apps/agentshield/internal/pending"
)

func TestPromotePendingToSignedReceipt(t *testing.T) {
	fx := newFixture(t, "block", nil, false)
	stateDir := t.TempDir()
	if err := pending.Append(stateDir, pending.Record{
		Platform: "hermes", Tool: "exec", SessionID: "sess-p",
		EnforcementMode: "block", Outcome: "deny",
		Reason: "decision service unavailable", RecordedAt: "2026-09-06T01:00:00Z",
	}); err != nil {
		t.Fatal(err)
	}
	if err := pending.Append(stateDir, pending.Record{
		Platform: "hermes", Tool: "web_fetch", SessionID: "sess-p",
		EnforcementMode: "audit_only", Outcome: "allow",
		Reason: "decision service unavailable", RecordedAt: "2026-09-06T01:00:01Z",
	}); err != nil {
		t.Fatal(err)
	}

	n, err := pending.Promote(stateDir, func(rec pending.Record) error {
		_, err := fx.eng.AppendPendingObserved(rec)
		return err
	})
	if err != nil || n != 2 {
		t.Fatalf("promote: n=%d err=%v", n, err)
	}
	recs, err := fx.chain.Read()
	if err != nil {
		t.Fatal(err)
	}
	if err := Verify(recs, fx.k.Public()); err != nil {
		t.Fatalf("chain verify: %v", err)
	}
	seq, _ := fx.chain.Head()
	if seq != 1 {
		t.Fatalf("head seq=%d want 1", seq)
	}

	n, err = pending.Promote(stateDir, func(rec pending.Record) error {
		_, err := fx.eng.AppendPendingObserved(rec)
		return err
	})
	if err != nil || n != 0 {
		t.Fatalf("idempotent: n=%d err=%v", n, err)
	}
	seq, _ = fx.chain.Head()
	if seq != 1 {
		t.Fatalf("idempotent must not grow chain, seq=%d", seq)
	}

	if len(recs) != 2 {
		t.Fatalf("want 2 receipts, got %d", len(recs))
	}
	if recs[0].Action != ActionDeny || recs[1].Action != ActionAllow {
		t.Fatalf("actions %s %s", recs[0].Action, recs[1].Action)
	}
	if len(recs[0].MatchedRuleIDs) == 0 || recs[0].MatchedRuleIDs[0] != "pending.fail_closed" {
		t.Fatalf("rule ids %+v", recs[0].MatchedRuleIDs)
	}
	if !VerifyHashSignature(fx.k.Public(), recs[0].Hash, recs[0].Sig) {
		t.Fatal("receipt signature invalid")
	}
}
