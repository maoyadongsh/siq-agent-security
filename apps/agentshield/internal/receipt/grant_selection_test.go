package receipt

import (
	"os"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
)

func TestRedactionUsesOnlySelectedGrant(t *testing.T) {
	for _, redaction := range []bool{false, true} {
		t.Run(map[bool]string{false: "cannot_borrow_redaction", true: "selected_redaction_without_legacy_lookup"}[redaction], func(t *testing.T) {
			selected := deployedGrant(t, "hermes", redaction)
			var legacy *grant.Grant
			if !redaction {
				legacy = deployedGrant(t, "hermes", true)
			}
			fx := newFixture(t, "block", legacy, false)
			store, err := intent.Open(t.TempDir(), fx.k, func(id string) (*grant.Grant, int, error) {
				if id != selected.GrantID {
					return nil, 0, os.ErrNotExist
				}
				return selected, 0, nil
			})
			if err != nil {
				t.Fatal(err)
			}
			c := intent.Contract{SchemaVersion: "intent/v2", IntentID: "int-selected", TaskID: "task-selected", Principal: intent.Principal{Type: "user", ID: "operator"}, Agent: intent.Agent{ID: "inst_1", Platform: "hermes"}, Purpose: "selected grant test", AllowedTools: []string{"web_fetch"}, AllowedEffects: []string{"network.request"}, ResourceConstraints: []intent.ResourceConstraint{}, ParameterConstraints: []intent.ParameterConstraint{}, IssuedAt: "2026-01-01T00:00:00Z", ValidFrom: "2026-01-01T00:00:00Z", ExpiresAt: "2099-01-01T00:00:00Z", Authority: intent.Authority{Issuer: "local-admin", Revision: "r1", EvidenceIDs: []string{}}}
			if _, err := store.Issue(c); err != nil {
				t.Fatal(err)
			}
			request := req("hermes", "web_fetch", map[string]any{"url": "https://api.github.com/report", "auth": "sk-" + strings.Repeat("A", 30)})
			if _, err := store.BindWithGrant(intent.Binding{Platform: request.Platform, AgentID: request.AgentID, SessionID: request.SessionID, IntentID: c.IntentID}, selected.GrantID, 0); err != nil {
				t.Fatal(err)
			}
			fx.eng.opts.IntentLookup = ResolveStore(store)
			d, err := fx.eng.Decide(request)
			if err != nil {
				t.Fatal(err)
			}
			want := ActionDeny
			if redaction {
				want = ActionRedact
			}
			if d.Action != want {
				t.Fatal("redaction selected another grant", d.Action)
			}
			if d.Receipt.MatchedGrantID == nil || *d.Receipt.MatchedGrantID != selected.GrantID {
				t.Fatal("wrong signed grant evidence")
			}
		})
	}
}
