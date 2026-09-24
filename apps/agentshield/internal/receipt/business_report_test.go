package receipt

import (
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func TestBusinessPublicationNeedsExplicitWritableRoot(t *testing.T) {
	for _, tc := range []struct {
		name, action, root string
		allowed            bool
	}{
		{"tool-only", "", "", false},
		{"read-only", "fs.read", runtimeaction.ResearchBusinessRoot, false},
		{"other-root", "fs.write", "/other/business", false},
		{"bound-write", "fs.write", runtimeaction.ResearchBusinessRoot, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			fact := func(domain, action, typ, value string) admission.DeclaredFact {
				return admission.DeclaredFact{Domain: domain, Action: action, Resource: admission.Resource{Type: typ, Value: value}, Effect: "allow", State: "declared", Authority: "skill_manifest", SourceField: "fixture", EvidenceIDs: []string{"ev-business"}}
			}
			facts := []admission.DeclaredFact{fact("tool", "tool.invoke", "tool", runtimeaction.ResearchPublishTool)}
			if tc.action != "" {
				facts = append(facts, fact("filesystem", tc.action, "path", tc.root))
			}
			adm := admission.Admission{AdmissionID: "adm-business", ContentHash: strings.Repeat("b", 64), Verdict: "admit_with_conditions", EvidenceIDs: []string{"ev-business"}, DeclaredFacts: facts}
			built, err := grant.Build(adm, grant.Options{Subject: grant.Subject{Type: "agent_instance", ID: "inst_1"}, Platform: "hermes", Key: key(t)})
			if err != nil {
				t.Fatal(err)
			}
			g, err := grant.Approve(built.Grant, grant.Approval{ActorType: "human", ActorID: "u", ApprovedAt: "2026-09-04T06:00:00Z"}, key(t))
			if err != nil {
				t.Fatal(err)
			}
			g, err = grant.MarkDeployed(g, key(t))
			if err != nil {
				t.Fatal(err)
			}
			fx := newFixture(t, "block", &g, false)
			d, err := fx.eng.Decide(req("hermes", runtimeaction.ResearchPublishTool, map[string]any{"task_id": "task-001", "request_sha256": strings.Repeat("a", 64), "approval_sha256": strings.Repeat("b", 64)}))
			if err != nil {
				t.Fatal(err)
			}
			if (d.Action == ActionAllow) != tc.allowed {
				t.Fatalf("unexpected scope permission: %s %s", d.Action, d.Receipt.ReasonCode)
			}
			if err := Verify([]Receipt{d.Receipt}, fx.k.Public()); err != nil {
				t.Fatal(err)
			}
		})
	}
}
