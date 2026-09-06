package ledger

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/inventory"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func TestConfirmDismissAndExpiry(t *testing.T) {
	dir := t.TempDir()
	st, err := state.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	home := t.TempDir()
	skill := filepath.Join(home, ".hermes", "skills", "demo")
	_ = os.MkdirAll(skill, 0o700)
	_ = os.WriteFile(filepath.Join(skill, "SKILL.md"), []byte("---\nname: demo\n---\n# d\n"), 0o600)
	rep, err := inventory.Run(inventory.Options{Home: home, Now: time.Date(2026, 9, 5, 8, 0, 0, 0, time.UTC), Version: "t", Key: key})
	if err != nil {
		t.Fatal(err)
	}
	snap := Snapshot{Report: rep}
	var id string
	for _, a := range Assets(snap) {
		if a.Name == "demo" {
			id = a.ID
		}
	}
	if id == "" {
		t.Fatal("demo missing")
	}
	if _, err := Dismiss(st, key, snap, id, "u", "", time.Now().Add(time.Hour).UTC().Format(time.RFC3339), time.Now().UTC()); err == nil {
		t.Fatal("dismiss without reason must fail")
	}
	until := time.Now().Add(time.Hour).UTC().Format(time.RFC3339)
	if _, err := Dismiss(st, key, snap, id, "u", "not us", until, time.Now().UTC()); err != nil {
		t.Fatal(err)
	}
	_ = Refresh(st, key, &snap, time.Now().UTC())
	row, ok := AssetByID(snap, id)
	if !ok || row.Status != "dismissed" {
		t.Fatalf("dismissed: %+v", row)
	}
	expired := time.Now().Add(-time.Hour).UTC().Format(time.RFC3339)
	if _, err := Dismiss(st, key, snap, id, "u", "old", expired, time.Now().UTC()); err != nil {
		t.Fatal(err)
	}
	_ = Refresh(st, key, &snap, time.Now().UTC())
	row, _ = AssetByID(snap, id)
	if row.Status == "dismissed" {
		t.Fatalf("expired dismiss must return to projection: %s", row.Status)
	}
	if _, err := Confirm(st, key, snap, id, "u", time.Now().UTC()); err != nil {
		t.Fatal(err)
	}
	_ = Refresh(st, key, &snap, time.Now().UTC())
	row, _ = AssetByID(snap, id)
	if row.Status != "confirmed" {
		t.Fatalf("confirmed: %s", row.Status)
	}
}

func TestHashChangeRevokesGrant(t *testing.T) {
	dir := t.TempDir()
	st, err := state.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(bytes.Repeat([]byte{8}, 32))
	home := t.TempDir()
	skill := filepath.Join(home, ".hermes", "skills", "demo")
	_ = os.MkdirAll(skill, 0o700)
	_ = os.WriteFile(filepath.Join(skill, "SKILL.md"), []byte("---\nname: demo\nallowed-tools: web_fetch\n---\n# d\n"), 0o600)
	rep, err := inventory.Run(inventory.Options{Home: home, Version: "t", Key: key})
	if err != nil {
		t.Fatal(err)
	}
	var hash, locator string
	for _, c := range rep.Candidates {
		if c.Name == "demo" {
			hash, locator = c.ArtifactDigest, c.SourceLocator
		}
	}
	adm := admission.Admission{AdmissionID: "adm-demo1", ContentHash: hash, Verdict: "admit", SkillName: "demo"}
	res, err := grant.Build(adm, grant.Options{Subject: grant.Subject{Type: "agent_instance", ID: "x"}, Platform: "hermes", Key: key})
	if err != nil {
		t.Fatal(err)
	}
	g, _ := grant.Approve(res.Grant, grant.Approval{ActorType: "human", ActorID: "u", ApprovedAt: time.Now().UTC().Format(time.RFC3339)}, key)
	g, _ = grant.MarkDeployed(g, key)
	_ = st.PutGrant(g)
	rec := AssetRecord{AssetID: "skill:hermes:demo@old", CandidateID: "skill:hermes:demo@old", SourceType: "skill_dir",
		SourceLocator: locator, Name: "demo", Framework: "hermes", Status: "admitted", AdmissionID: adm.AdmissionID,
		GrantID: g.GrantID, ContentHash: hash, UpdatedAt: time.Now().UTC().Format(time.RFC3339)}
	_ = putAsset(st, key, rec)
	_ = os.WriteFile(filepath.Join(skill, "SKILL.md"), []byte("---\nname: demo\nallowed-tools: web_fetch\n---\n# changed\n"), 0o600)
	rep2, _ := inventory.Run(inventory.Options{Home: home, Version: "t", Key: key})
	snap := Snapshot{Report: rep2, Admissions: []admission.Admission{adm}, Grants: []grant.Grant{g}}
	if err := Refresh(st, key, &snap, time.Now().UTC()); err != nil {
		t.Fatal(err)
	}
	revoked := false
	for _, gg := range snap.Grants {
		if gg.GrantID == g.GrantID && gg.Status == "revoked" {
			revoked = true
		}
	}
	if !revoked {
		t.Fatalf("grant must be revoked after hash change: %+v", snap.Grants)
	}
	foundReview := false
	for _, a := range Assets(snap) {
		if a.SourceType == "skill_dir" && a.Name == "demo" && a.Status == "needs_review" {
			foundReview = true
		}
	}
	if !foundReview {
		t.Fatalf("live skill must be needs_review: %+v", Assets(snap))
	}
}

func TestMissingDirMarksStale(t *testing.T) {
	dir := t.TempDir()
	st, _ := state.Open(dir)
	key, _ := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	rec := AssetRecord{CandidateID: "skill:hermes:gone@abc", SourceType: "skill_dir", SourceLocator: "hermes://skills/~/x",
		Name: "gone", Framework: "hermes", Status: "admitted", UpdatedAt: time.Now().UTC().Format(time.RFC3339)}
	_ = putAsset(st, key, rec)
	home := t.TempDir()
	rep, _ := inventory.Run(inventory.Options{Home: home, Version: "t", Key: key})
	snap := Snapshot{Report: rep}
	_ = Refresh(st, key, &snap, time.Now().UTC())
	row, ok := AssetByID(snap, rec.CandidateID)
	if row.Status != "stale" {
		t.Fatalf("stale: ok=%v %+v", ok, row)
	}
}

func TestAcceptFindingExpires(t *testing.T) {
	dir := t.TempDir()
	st, _ := state.Open(dir)
	key, _ := signing.FromSeed(bytes.Repeat([]byte{11}, 32))
	adm := admission.Admission{
		AdmissionID: "adm-f", SkillName: "demo",
		Findings: []admission.Finding{{FindingID: "f-1", RuleID: "r1", Category: "c", Severity: "high", Disposition: "review"}},
	}
	snap := Snapshot{Admissions: []admission.Admission{adm}}
	until := time.Now().Add(time.Hour).UTC().Format(time.RFC3339)
	if _, err := AcceptFinding(st, key, snap, "f-1", "u", "accepted risk", until, time.Now().UTC()); err != nil {
		t.Fatal(err)
	}
	_ = Refresh(st, key, &snap, time.Now().UTC())
	var got FindingRow
	for _, f := range Findings(snap) {
		if f.FindingID == "f-1" {
			got = f
		}
	}
	if got.Status != "accepted" {
		t.Fatalf("accepted: %+v", got)
	}
	expired := time.Now().Add(-time.Hour).UTC().Format(time.RFC3339)
	if _, err := AcceptFinding(st, key, snap, "f-1", "u", "old", expired, time.Now().UTC()); err != nil {
		t.Fatal(err)
	}
	_ = Refresh(st, key, &snap, time.Now().UTC())
	for _, f := range Findings(snap) {
		if f.FindingID == "f-1" && f.Status != "open" {
			t.Fatalf("expired accept must be open: %+v", f)
		}
	}
}
