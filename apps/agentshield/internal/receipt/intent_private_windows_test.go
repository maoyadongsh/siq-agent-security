package receipt

import (
	"path/filepath"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/intent"
)

func TestWindowsIntentACLDriftAlwaysProducesSignedDeny(t *testing.T) {
	for _, enforcement := range []string{"optional", "required"} {
		for _, mode := range []string{"block", "warn", "audit_only"} {
			t.Run(enforcement+"/"+mode, func(t *testing.T) {
				fx := newFixture(t, mode, deployedGrant(t, "hermes", false), false)
				fx.clock = time.Now().UTC()
				root := t.TempDir()
				store, err := intent.Open(root, fx.k)
				if err != nil {
					t.Fatal(err)
				}
				c := intent.Contract{SchemaVersion: "intent/v2", IntentID: "int-acl", TaskID: "task-acl", Principal: intent.Principal{Type: "user", ID: "fixture-human"}, Agent: intent.Agent{ID: "inst_1", Platform: "hermes"}, Purpose: "read fixture", AllowedTools: []string{"read_file"}, AllowedEffects: []string{"file.read"}, ResourceConstraints: []intent.ResourceConstraint{}, ParameterConstraints: []intent.ParameterConstraint{}, IssuedAt: "2026-01-01T00:00:00Z", ValidFrom: "2026-01-01T00:00:00Z", ExpiresAt: "2099-01-01T00:00:00Z", Authority: intent.Authority{Issuer: "local-admin", Revision: "r1", EvidenceIDs: []string{}}}
				if _, err := store.Issue(c); err != nil {
					t.Fatal(err)
				}
				binding, err := store.Bind(intent.Binding{Platform: "hermes", SessionID: "sess-1", AgentID: "inst_1", IntentID: c.IntentID})
				if err != nil {
					t.Fatal(err)
				}
				fx.eng.opts.IntentLookup = ResolveStore(store)
				fx.eng.opts.IntentEnforcement = enforcement
				request := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/a.txt"})
				for _, path := range []string{filepath.Join(root, "intent-bindings", binding.BindingID+".json"), filepath.Join(root, "intent-binding-revocations")} {
					baseline, err := fx.eng.Decide(request)
					if err != nil || baseline.Action != ActionAllow {
						t.Fatal("safe authority rejected", err)
					}
					restore := acltest.BroadenRead(t, root, path)
					denied, err := fx.eng.Decide(request)
					if err != nil || denied.Action != ActionDeny || denied.Receipt.AdvisoryAction != nil || denied.Receipt.AuthorityStatus != "invalid" || denied.Receipt.EffectiveAction != ActionDeny || denied.Receipt.Sig == "" {
						t.Fatal("private authority failure allowed or was not signed", denied, err)
					}
					restore()
				}
				entries, err := fx.chain.Read()
				if err != nil || Verify(entries, fx.k.Public()) != nil {
					t.Fatal("denial receipt chain invalid", err)
				}
			})
		}
	}
}
