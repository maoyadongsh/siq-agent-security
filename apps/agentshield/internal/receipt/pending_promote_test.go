package receipt

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/pending"
)

func TestLocalPendingPromotionPreservesOriginAndDoesNotBackdate(t *testing.T) {
	fx := newFixture(t, "block", nil, false)
	for _, outcome := range []string{"deny", "unconfirmed"} {
		p := pending.Record{Schema: pending.LocalSchemaID, Platform: "workbuddy", RecordedAt: fx.clock.Add(-time.Hour).Format(time.RFC3339Nano), EnforcementMode: "block", Outcome: outcome, Reason: "managed observation unavailable", Origin: "local_hook", Stage: "observation", ReasonCode: "workbuddy_observation_unconfirmed"}
		rec, err := fx.eng.AppendPendingObserved(p)
		if err != nil {
			t.Fatal(err)
		}
		if rec.RecordType != "local_failure" || rec.SchemaVersion != "runtime-receipt/v2" || rec.LocalOrigin == nil || rec.LocalOrigin.RecordedAt != p.RecordedAt || rec.IssuedAt == p.RecordedAt || rec.LocalOrigin.Signed {
			t.Fatal("local origin/time lost", rec)
		}
		if rec.AuthorityStatus != "" || rec.PolicyAction != "" || rec.EffectiveAction != "" || rec.MatchedGrantID != nil || rec.ToolCallID != nil || rec.SessionID != "" {
			t.Fatal("promotion fabricated online authority/correlation")
		}
		if outcome == "unconfirmed" && rec.Action != "unknown" {
			t.Fatal("unconfirmed observation reported as decision")
		}
		if outcome == "deny" && rec.Action != "deny" {
			t.Fatal("local deny changed")
		}
		if !VerifyHashSignature(fx.k.Public(), rec.Hash, rec.Sig) {
			t.Fatal("promotion unsigned")
		}
		if outcome == "unconfirmed" {
			if os.Getenv("SIQ_UPDATE_CONTRACT_FIXTURES") == "1" {
				raw, err := json.MarshalIndent(rec, "", "  ")
				if err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join("..", "..", "testdata", "contracts", "receipt-local-failure-v2.json"), append(raw, '\n'), 0600); err != nil {
					t.Fatal(err)
				}
			}
		}
	}
	records, err := fx.chain.Read()
	if err != nil || Verify(records, fx.k.Public()) != nil {
		t.Fatal("mixed event chain invalid", err)
	}
	records[0].LocalOrigin.ReasonCode = "tampered_local_reason"
	if Verify(records, fx.k.Public()) == nil {
		t.Fatal("local origin excluded from hash/signature")
	}
}

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
