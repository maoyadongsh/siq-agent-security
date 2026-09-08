package receipt

import (
	"siq-agent-security/apps/agentshield/internal/grant"
	"testing"
)

func TestGlobalIntentRevocationHardDeniesEveryModeAfterRestart(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		for _, enforcement := range []string{"required", "optional"} {
			t.Run(mode+"/"+enforcement, func(t *testing.T) {
				fx, store, b := revocableEngine(t, enforcement, mode)
				r := req("hermes", "read_file", map[string]any{"path": "/work/report"})
				before, err := fx.eng.Decide(r)
				if err != nil || before.Action != ActionAllow {
					t.Fatal("normal authority rejected", err)
				}
				if _, err = store.RevokeIntent(b.IntentID, b.IntentDigest); err != nil {
					t.Fatal(err)
				}
				for i := 0; i < 2; i++ {
					denied, err := fx.eng.Decide(r)
					if err != nil || denied.Action != ActionDeny || denied.Receipt.AuthorityReasonCode != "intent_revoked" || denied.Receipt.PolicyAction != "" || denied.Receipt.AdvisoryAction != nil || denied.Receipt.TaskID != before.Receipt.TaskID {
						t.Fatal("global revocation downgraded or lost task", denied, err)
					}
					fx.eng, err = New(fx.eng.opts)
					if err != nil {
						t.Fatal(err)
					}
				}
			})
		}
	}
}

func TestGlobalIntentRevocationInvalidatesApprovedHold(t *testing.T) {
	fx, store, b := revocableEngine(t, "required", "block")
	g := deployedGrant(t, "hermes", false)
	g.OpenClawToolPolicy = &grant.OpenClawToolPolicy{RequireApproval: []string{"read_file"}}
	fx.eng.opts.Grants = func(_, _ string) *grant.Grant { return g }
	r := req("hermes", "read_file", map[string]any{"path": "/work/report"})
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionHold {
		t.Fatal("expected real hold", d, err)
	}
	if _, err = fx.eng.ResolveHold(d.Receipt, true, "fixture-admin"); err != nil {
		t.Fatal(err)
	}
	request := statusRequest(r, d)
	status, err := fx.eng.ReadHoldStatus(request)
	if err != nil || status.Status != "approved" {
		t.Fatal(status, err)
	}
	if _, err = store.RevokeIntent(b.IntentID, b.IntentDigest); err != nil {
		t.Fatal(err)
	}
	status, err = fx.eng.ReadHoldStatus(request)
	if err != nil || status.Status != "denied" {
		t.Fatal("global revocation retained approved hold", status, err)
	}
}
