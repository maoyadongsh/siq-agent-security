package receipt

import (
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func TestReportGenerationRequiresEveryScope(t *testing.T) {
	for _, missing := range []string{"none", "tool", "company", "metadata", "output", "network"} {
		t.Run(missing, func(t *testing.T) {
			root := filepath.ToSlash(t.TempDir())
			company := root + "/data/wiki/companies/600418-example"
			run := "qwen-request-0123456789abcdef"
			facts := []admission.DeclaredFact{}
			add := func(label, domain, action, typ, value string) {
				if label != missing {
					facts = append(facts, admission.DeclaredFact{Domain: domain, Action: action,
						Resource: admission.Resource{Type: typ, Value: value}, Effect: "allow", State: "declared", Authority: "skill_manifest", SourceField: "fixture", EvidenceIDs: []string{"ev-generate"}})
				}
			}
			add("tool", "tool", "tool.invoke", "tool", runtimeaction.ResearchGenerateTool)
			add("company", "filesystem", "fs.read", "path", company)
			add("metadata", "filesystem", "fs.read", "path", root+"/data/wiki/_meta")
			add("output", "filesystem", "fs.write", "path", company+"/analysis/runs/"+run)
			add("network", "network", "net.connect", "endpoint", runtimeaction.ResearchGenerateBroker)
			adm := admission.Admission{AdmissionID: "adm-generate", ContentHash: strings.Repeat("b", 64), Verdict: "admit_with_conditions", EvidenceIDs: []string{"ev-generate"}, DeclaredFacts: facts}
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
			d, err := fx.eng.Decide(req("hermes", runtimeaction.ResearchGenerateTool, map[string]any{"company_path": company, "run_id": run, "year": 2025}))
			if err != nil {
				t.Fatal(err)
			}
			if (d.Action == ActionAllow) != (missing == "none") {
				t.Fatalf("scope %s: %s %s", missing, d.Action, d.Receipt.ReasonCode)
			}
			if err := Verify([]Receipt{d.Receipt}, fx.k.Public()); err != nil {
				t.Fatal(err)
			}
		})
	}
}
