package inventory

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func skillsByPath(report *Report) map[string]Candidate {
	out := map[string]Candidate{}
	for _, candidate := range report.Candidates {
		if candidate.SourceType == "skill_dir" {
			out[SkillLocation(candidate.SourceLocator)] = candidate
		}
	}
	return out
}

func TestSkillInstallationIdentitySurvivesContentChange(t *testing.T) {
	home := t.TempDir()
	left := filepath.Join(home, ".hermes", "skills", "first", "same")
	right := filepath.Join(home, ".hermes", "skills", "second", "same")
	for _, path := range []string{left, right} {
		write(t, filepath.Join(path, "SKILL.md"), "---\nname: same\n---\nVersion A\n")
	}
	first := skillsByPath(runInv(t, home))
	if len(first) != 2 {
		t.Fatal("nested same-name installations were merged or missed")
	}
	a, b := first["~/.hermes/skills/first/same"], first["~/.hermes/skills/second/same"]
	if a.CandidateID == b.CandidateID || a.ArtifactDigest != b.ArtifactDigest {
		t.Fatal("directory identity must be independent of name and content")
	}
	write(t, filepath.Join(left, "SKILL.md"), "---\nname: renamed\n---\nVersion B\n")
	second := skillsByPath(runInv(t, home))
	changed := second["~/.hermes/skills/first/same"]
	if a.CandidateID != changed.CandidateID || a.ArtifactDigest == changed.ArtifactDigest {
		t.Fatal("update changed installation identity or failed to observe content")
	}
	if len(second) != 2 {
		t.Fatal("update created another installation")
	}
}

func TestSharedSkillsRetainMultipleConsumers(t *testing.T) {
	home := t.TempDir()
	write(t, filepath.Join(home, ".openclaw", "openclaw.json"), `{"agents":{"list":[{"id":"one","workspace":"~/.openclaw/workspace-one"},{"id":"two","workspace":"~/.openclaw/workspace-two"}]}}`)
	write(t, filepath.Join(home, ".openclaw", "skills", "shared", "SKILL.md"), "---\nname: shared\n---\n")
	write(t, filepath.Join(home, ".openclaw", "workspace-one", "skills", "private", "SKILL.md"), "---\nname: private\n---\n")
	report := runInv(t, home)
	skills := skillsByPath(report)
	shared := skills["~/.openclaw/skills/shared"].CandidateID
	private := skills["~/.openclaw/workspace-one/skills/private"].CandidateID
	if shared == "" || private == "" {
		t.Fatal("shared or configured workspace Skill missing")
	}
	consumers := map[string][]string{}
	for _, relationship := range report.Relationships {
		if relationship.State != "inferred" || len(relationship.EvidenceIDs) == 0 {
			t.Fatal("configuration relationship claims runtime authority or lacks evidence")
		}
		consumers[relationship.SkillID] = append(consumers[relationship.SkillID], relationship.SourceID)
	}
	if len(consumers[shared]) != 2 || len(consumers[private]) != 1 || consumers[private][0] != "agent:openclaw:one" {
		t.Fatal("shared/workspace consumers are incorrect")
	}
}

func TestHermesProfileSkillsAreIsolatedAndNeverExecuted(t *testing.T) {
	home := t.TempDir()
	marker := filepath.Join(home, "must-not-exist")
	write(t, filepath.Join(home, ".hermes", "config.yaml"), "model: test\n")
	write(t, filepath.Join(home, ".hermes", "skills", "default-only", "SKILL.md"), "---\nname: default-only\n---\n")
	write(t, filepath.Join(home, ".hermes", "profiles", "work", "config.yaml"), "model: test\n")
	base := filepath.Join(home, ".hermes", "profiles", "work", "skills", "category", "work-only")
	write(t, filepath.Join(base, "SKILL.md"), "---\nname: work-only\n---\n")
	write(t, filepath.Join(base, "scripts", "run.sh"), "touch "+marker+"\n")
	report := runInv(t, home)
	skills := skillsByPath(report)
	for _, relationship := range report.Relationships {
		if relationship.SkillID == skills["~/.hermes/skills/default-only"].CandidateID && relationship.SourceID != "agent:hermes:default" {
			t.Fatal("default skills leaked into another profile")
		}
		if relationship.SkillID == skills["~/.hermes/profiles/work/skills/category/work-only"].CandidateID && relationship.SourceID != "agent:hermes:work" {
			t.Fatal("profile skill leaked into another profile")
		}
	}
	if len(report.Relationships) != 2 {
		t.Fatal("profile relationship missing")
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("discovered script executed")
	}
}

func TestCustomHermesHomeUsesSameInstanceIdentityAndSeparateConsumers(t *testing.T) {
	home := t.TempDir()
	legacy := filepath.Join(home, ".hermes", "profiles", "work")
	custom := filepath.Join(home, "custom-root", "profiles", "work")
	for _, root := range []string{legacy, custom} {
		write(t, filepath.Join(root, "config.yaml"), "model: fixture\n")
		write(t, filepath.Join(root, "skills", "same", "SKILL.md"), "---\nname: same\n---\n")
	}
	key, _ := signing.FromSeed(bytes.Repeat([]byte{4}, 32))
	report, err := Run(Options{Home: home, HermesHome: custom, Key: key})
	if err != nil {
		t.Fatal(err)
	}
	wanted := map[string]string{}
	for _, root := range hermeshome.Scan(hermeshome.Options{Home: home, Override: custom}).Roots {
		if root.Path == custom || root.Path == legacy {
			wanted[root.CandidateID] = root.ID
		}
	}
	found := map[string]bool{}
	for _, candidate := range report.Candidates {
		if id, ok := wanted[candidate.CandidateID]; ok {
			if candidate.Attributes["instance_id"] != id {
				t.Fatal("inventory and installer disagree on instance identity")
			}
			found[candidate.CandidateID] = true
		}
	}
	if len(found) != 2 || len(report.Relationships) != 2 || report.Relationships[0].SourceID == report.Relationships[1].SourceID || report.Relationships[0].SkillID == report.Relationships[1].SkillID {
		t.Fatal("same-name profiles or Skill consumers merged")
	}
	invalid, err := Run(Options{Home: home, HermesHome: "relative-profile", Key: key})
	if err != nil {
		t.Fatal(err)
	}
	if len(invalid.Relationships) != 0 || len(invalid.Skipped) == 0 {
		t.Fatal("invalid active root silently fell back to another profile")
	}
}

func TestDiscoveryRejectsSymlinkAndOversizedConfig(t *testing.T) {
	home := t.TempDir()
	external := t.TempDir()
	write(t, filepath.Join(external, "SKILL.md"), "---\nname: external\n---\n")
	if err := os.MkdirAll(filepath.Join(home, ".hermes", "skills"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(external, filepath.Join(home, ".hermes", "skills", "linked")); err != nil {
		t.Skip("symlink creation unavailable on this OS")
	}
	write(t, filepath.Join(home, ".openclaw", "openclaw.json"), strings.Repeat("x", maxDiscoveryConfig+1))
	report := runInv(t, home)
	if len(report.Candidates) != 0 || len(report.Skipped) < 2 {
		t.Fatal("unsafe or oversize source accepted or silently omitted")
	}
	raw, _ := json.Marshal(report)
	if strings.Contains(string(raw), external) {
		t.Fatal("symlink destination leaked into report")
	}
}

func TestHomeRedactionUsesPathBoundary(t *testing.T) {
	if got := redactHome("/home/alice-other/skill", "/home/alice"); got != "/home/alice-other/skill" {
		t.Fatal("redaction conflated two different directories")
	}
	if InstallationID("hermes://skills/~/.hermes/skills/example") != InstallationID("local://skills/~/.hermes/skills/example") {
		t.Fatal("legacy prefix changes installation identity")
	}
}
