package ledger

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/inventory"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func TestLegacySkillMigrationKeepsApprovalAndOldLink(t *testing.T) {
	home := t.TempDir()
	skill := filepath.Join(home, ".hermes", "skills", "example")
	if err := os.MkdirAll(skill, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(skill, "SKILL.md"), []byte("---\nname: example\n---\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	report, err := inventory.Run(inventory.Options{Home: home, Key: key, Version: "test"})
	if err != nil {
		t.Fatal(err)
	}
	candidate := report.Candidates[0]
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	admit := admission.Admission{AdmissionID: "adm-migration", ContentHash: candidate.ArtifactDigest, Verdict: "admit", SkillName: "example"}
	built, err := grant.Build(admit, grant.Options{Subject: grant.Subject{Type: "agent_instance", ID: "profile"}, Platform: "hermes", Key: key})
	if err != nil {
		t.Fatal(err)
	}
	g, err := grant.Approve(built.Grant, grant.Approval{ActorType: "human", ActorID: "user", ApprovedAt: time.Now().UTC().Format(time.RFC3339)}, key)
	if err != nil {
		t.Fatal(err)
	}
	g, err = grant.MarkDeployed(g, key)
	if err != nil {
		t.Fatal(err)
	}
	if err := st.PutGrant(g); err != nil {
		t.Fatal(err)
	}
	oldID := "skill:hermes:example@" + candidate.ArtifactDigest[:12]
	record := AssetRecord{AssetID: oldID, CandidateID: oldID, SourceType: "skill_dir", SourceLocator: strings.Replace(candidate.SourceLocator, "local://", "hermes://", 1),
		Name: candidate.Name, Framework: "hermes", Status: "confirmed", ContentHash: candidate.ArtifactDigest, AdmissionID: admit.AdmissionID, GrantID: g.GrantID,
		ActorID: "user", UpdatedAt: time.Now().UTC().Format(time.RFC3339)}
	if err := putAsset(st, key, record); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		snap := Snapshot{Report: report, Admissions: []admission.Admission{admit}, Grants: []grant.Grant{g}}
		if err := Refresh(st, key, &snap, time.Now().UTC()); err != nil {
			t.Fatal(err)
		}
		assets := Assets(snap)
		if len(assets) != 1 || assets[0].ID != candidate.CandidateID || assets[0].Status != "confirmed" {
			t.Fatal("migration duplicated or unconfirmed installation")
		}
		if len(snap.Grants) != 1 || snap.Grants[0].Status != "deployed" {
			t.Fatal("identity-only migration revoked an unchanged grant")
		}
		if detail, ok := AssetByID(snap, oldID); !ok || detail.ID != candidate.CandidateID {
			t.Fatal("legacy link no longer resolves to the installation")
		}
	}
}
