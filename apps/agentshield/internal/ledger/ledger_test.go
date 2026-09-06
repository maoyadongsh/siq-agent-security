package ledger

import (
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/inventory"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

func TestPermissionsNeverPromotesDeployedToEffective(t *testing.T) {
	rev := "2"
	s := Snapshot{
		Grants: []grant.Grant{{
			GrantID: "grt-1", AdmissionID: "adm-1", Status: "deployed",
			Subject: grant.Subject{Type: "agent_instance", ID: "inst_1"},
			Facts: []grant.Fact{
				{FactID: "pf-tool", Domain: "tool", Action: "tool.invoke", Resource: admission.Resource{Type: "tool", Value: "web_fetch"}, Effect: "allow", State: StateDeclared, Authority: "skill_manifest"},
				{FactID: "pf-net", Domain: "network", Action: "http.request", Resource: admission.Resource{Type: "endpoint", Value: "api.github.com:443"}, Effect: "allow", State: StateDeclared, Authority: "skill_manifest"},
			},
		}},
	}
	rows := Permissions(s, "")
	for _, r := range rows {
		if r.State == StateEffective {
			t.Fatalf("deployed grant must not project effective, got %+v", r)
		}
	}
	s.Grants[0].Status = "effective"
	s.Grants[0].Facts[1].State = StateEffective
	s.Grants[0].Facts[1].Authority = "openshell"
	s.Grants[0].Facts[1].AuthorityRevision = &rev
	rows = Permissions(s, "inst_1")
	var sawEffective, sawDeclared bool
	for _, r := range rows {
		if r.FactID == "pf-net" && r.State == StateEffective && r.AuthorityRevision != nil && *r.AuthorityRevision == "2" {
			sawEffective = true
		}
		if r.FactID == "pf-tool" && r.State == StateDeclared {
			sawDeclared = true
		}
	}
	if !sawEffective || !sawDeclared {
		t.Fatalf("effective network + declared tool: effective=%v declared=%v rows=%+v", sawEffective, sawDeclared, rows)
	}
}

func TestFilesystemEffectiveIsCoerced(t *testing.T) {
	s := Snapshot{
		Grants: []grant.Grant{{
			GrantID: "grt-fs", Status: "effective",
			Subject:          grant.Subject{Type: "agent_instance", ID: "x"},
			DesiredPolicyRef: &grant.DesiredPolicyRef{StaticDomainsUnavailable: []string{"filesystem", "process"}},
			Facts: []grant.Fact{
				{FactID: "pf-fs", Domain: "filesystem", Action: "fs.write", Resource: admission.Resource{Type: "path", Value: "/tmp"}, Effect: "allow", State: StateEffective, Authority: "openshell"},
			},
		}},
	}
	rows := Permissions(s, "")
	var fsState, unknown bool
	for _, r := range rows {
		if r.FactID == "pf-fs" {
			if r.State == StateEffective {
				t.Fatal("filesystem must never be effective")
			}
			fsState = true
		}
		if r.State == StateUnknown && r.Domain == "process" {
			unknown = true
		}
	}
	if !fsState || !unknown {
		t.Fatalf("want coerced fs + unknown process, rows=%+v", rows)
	}
}

func TestReceiptsAreObservedOnly(t *testing.T) {
	agent := "inst_1"
	s := Snapshot{
		Receipts: []receipt.Receipt{{
			ReceiptID: "rcp-1", Action: "deny", Tool: "web_fetch", AgentID: &agent, SessionID: "s",
		}},
	}
	rows := Permissions(s, "inst_1")
	if len(rows) != 1 || rows[0].State != StateObserved || rows[0].Effect != "deny" {
		t.Fatalf("observed deny: %+v", rows)
	}
}

func TestAssetsUnadmittedAndLinkedAdmission(t *testing.T) {
	s := Snapshot{
		Report: &inventory.Report{
			GeneratedAt: "2026-09-05T00:00:00Z",
			Candidates: []inventory.Candidate{
				{CandidateID: "platform:hermes", Name: "hermes", Framework: "hermes", SourceType: "platform_config", SourceLocator: "hermes://.hermes/config.yaml", Status: "candidate"},
				{CandidateID: "skill:hermes:demo@abc", Name: "demo", Framework: "hermes", SourceType: "skill_dir",
					SourceLocator: "hermes://skills/~/.hermes/skills/demo", ArtifactDigest: "hash1",
					Attributes:  map[string]string{"platform": "hermes", "dir": "demo", "allowed_tools": "web_fetch terminal"},
					EvidenceIDs: []string{"ev-1"}},
			},
			Evidence: []admission.Evidence{{EvidenceID: "ev-1", SourceType: "skill_dir", ContentHash: "hash1"}},
		},
		Admissions: []admission.Admission{{
			AdmissionID: "adm-1", SkillName: "demo", ContentHash: "hash1", Verdict: "admit_with_conditions",
			DeclaredFacts: []admission.DeclaredFact{{Domain: "tool", Action: "tool.invoke", Resource: admission.Resource{Type: "tool", Value: "web_fetch"}}},
		}},
		Grants: []grant.Grant{{GrantID: "grt-1", AdmissionID: "adm-1", Status: "pending_approval", CreatedAt: "2026-09-05T01:00:00Z"}},
	}
	list := Assets(s)
	if list[0].Status != "candidate" {
		t.Fatalf("platform status: %s", list[0].Status)
	}
	sk := list[1]
	if sk.Status != "admitted" || sk.AdmissionID != "adm-1" || sk.GrantID != "grt-1" {
		t.Fatalf("skill link: %+v", sk)
	}
	if sk.AdmitPath != "~/.hermes/skills/demo" {
		t.Fatalf("admit_path: %s", sk.AdmitPath)
	}
	detail, ok := AssetByID(s, "skill:hermes:demo@abc")
	if !ok || len(detail.Evidence) != 1 || detail.Admission == nil || len(detail.Grants) != 1 {
		t.Fatalf("detail: ok=%v %+v", ok, detail)
	}
}

func TestFindingsAndCounts(t *testing.T) {
	s := Snapshot{
		Report: &inventory.Report{Candidates: []inventory.Candidate{
			{CandidateID: "skill:x", SourceType: "skill_dir", Attributes: map[string]string{"admission_verdict": "none"}},
		}},
		Admissions: []admission.Admission{{
			AdmissionID: "adm-q", SkillName: "bad",
			Findings: []admission.Finding{{FindingID: "f1", RuleID: "threat-x", Severity: "high", Disposition: "quarantine"}},
		}},
		Receipts: []receipt.Receipt{{Action: "deny"}, {Action: "allow"}},
		Grants:   []grant.Grant{{Status: "deployed"}},
	}
	f := Findings(s)
	if len(f) != 1 || f[0].Status != "open" {
		t.Fatalf("findings: %+v", f)
	}
	c := Counts(s)
	if c.UnadmittedSkills != 1 || c.OpenFindings != 1 || c.RecentDenies != 1 || c.GrantsDeployed != 1 {
		t.Fatalf("counts: %+v", c)
	}
}
