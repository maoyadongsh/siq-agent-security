package receipt

import (
	"siq-agent-security/apps/agentshield/internal/intent"
	"testing"
)

func TestOpenClawLegacySessionHardDeniedAndEpochCanExecute(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		t.Run(mode, func(t *testing.T) {
			fx := newFixture(t, mode, deployedGrant(t, "openclaw", false), false)
			r := req("openclaw", "read_file", map[string]any{"path": "/home/u/proj/file.txt"})
			r.SessionID = "agent:fixture:main"
			denied, err := fx.eng.Decide(r)
			if err != nil || denied.Action != ActionDeny || denied.Receipt.ReasonCode != "native_session_epoch_required" {
				t.Fatalf("legacy was not hard denied: %+v %v", denied, err)
			}
			r.SessionID, err = intent.OpenClawSessionID("agent:fixture:main", "11111111-1111-4111-8111-111111111111")
			if err != nil {
				t.Fatal(err)
			}
			allowed, err := fx.eng.Decide(r)
			if err != nil || allowed.Action != ActionAllow {
				t.Fatalf("new epoch was not allowed: %+v %v", allowed, err)
			}
			observed := correlatedRequest(r, allowed)
			observed.SessionID, _ = intent.OpenClawSessionID("agent:fixture:main", "22222222-2222-4222-8222-222222222222")
			if _, err = fx.eng.Observe(observed, "forged cross epoch"); err == nil {
				t.Fatal("cross epoch observation accepted")
			}
			if _, err = fx.eng.Observe(correlatedRequest(r, allowed), "actual result"); err != nil {
				t.Fatal("valid observation rejected", err)
			}
		})
	}
}
