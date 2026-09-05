package export

import (
	"bytes"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/inventory"
	"siq-agent-security/apps/agentshield/internal/ledger"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func TestBuildOmitsParamsAndPrivateMaterial(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	chain, err := receipt.OpenChain(t.TempDir(), "local", key)
	if err != nil {
		t.Fatal(err)
	}
	excerpt := "Authorization: Bearer supersecrettokenvalue"
	r := receipt.Receipt{
		Platform: "hermes", SessionID: "s1", Tool: "web_fetch", Action: "deny",
		Reason: "tool not granted", ParamsDigest: strings.Repeat("ab", 32), ParamsExcerpt: &excerpt,
		EnforcementMode: "block",
	}
	if err := chain.Append(&r); err != nil {
		t.Fatal(err)
	}
	recs, err := chain.Read()
	if err != nil {
		t.Fatal(err)
	}
	snap := ledger.Snapshot{
		Report: &inventory.Report{GeneratedAt: "2026-09-05T00:00:00Z", Platforms: []string{"hermes"}},
		Admissions: []admission.Admission{{
			AdmissionID: "adm-1", SkillName: "demo", Verdict: "quarantine", ContentHash: strings.Repeat("cd", 32),
			Findings: []admission.Finding{{FindingID: "f-1", RuleID: "threat-x", Excerpt: &excerpt}},
		}},
		Grants: []grant.Grant{{
			GrantID: "grt-1", Status: "deployed", Platform: "hermes",
			Subject: grant.Subject{ID: "demo"}, AdmissionID: "adm-1",
			Facts: []grant.Fact{{Domain: "tool", Action: "invoke", Resource: admission.Resource{Value: "web_fetch"}, Effect: "deny", State: "declared"}},
		}},
		Receipts: recs,
	}
	b := Build(Input{
		Now: "2026-09-05T12:00:00Z", Mode: "block", Key: key, Snap: snap,
		Audit: []state.AuditEvent{{At: "2026-09-05T12:00:00Z", Event: "asset_confirm", ActorID: "local", Target: "agent:hermes:demo"}},
	})
	if !b.ChainVerified {
		t.Fatalf("chain should verify: %s", b.ChainVerifyError)
	}
	raw, err := MarshalJSONBytes(b)
	if err != nil {
		t.Fatal(err)
	}
	s := string(raw)
	if !strings.Contains(s, `"format": "agentshield.export.v1"`) {
		t.Fatalf("format missing")
	}
	if strings.Contains(s, excerpt) || strings.Contains(s, "params_excerpt") || strings.Contains(s, "supersecrettokenvalue") {
		t.Fatal("params excerpt / secret token must not appear")
	}
	if ContainsForbidden(raw, excerpt, "params_excerpt") {
		t.Fatal("forbidden needle")
	}
	if len(b.Findings) != 1 || b.Findings[0].Excerpt != nil {
		t.Fatalf("finding excerpt must be stripped: %+v", b.Findings)
	}
	if b.Identity.PublicKeyBase64 == "" {
		t.Fatal("pubkey required")
	}
	if len(b.Receipts) != 1 || b.Receipts[0].Action != "deny" {
		t.Fatalf("receipts: %+v", b.Receipts)
	}
}
