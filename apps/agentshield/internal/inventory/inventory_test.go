package inventory

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
)

func write(t *testing.T, path, content string) {
	t.Helper()
	_ = os.MkdirAll(filepath.Dir(path), 0o700)
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
}

const secretMarker = "sk-SECRETSECRETSECRETSECRET"

func fakeHome(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	write(t, filepath.Join(home, ".hermes", "config.yaml"), "model: x\nplugins:\n  - agentshield\n")
	write(t, filepath.Join(home, ".hermes", ".env"), "OPENAI_API_KEY="+secretMarker+"\n")
	write(t, filepath.Join(home, ".hermes", "skills", "report-beautifier", "SKILL.md"), "---\nname: report-beautifier\ndescription: Beautify.\nallowed-tools: terminal\n---\n# x\n")
	write(t, filepath.Join(home, ".hermes", "skills", "report-beautifier", "scripts", "run.sh"), "echo "+secretMarker+"\n")
	write(t, filepath.Join(home, ".hermes", "skills", "not-a-skill", "README.md"), "no SKILL.md here\n")
	write(t, filepath.Join(home, ".openclaw", "openclaw.json"), `{"security":{"installPolicy":{"enabled":true,"exec":{"command":"/usr/local/bin/agentshield","args":["policy-exec"]}}},"plugins":{"entries":{"agentshield":{"enabled":true}}},"apiKey":"`+secretMarker+`"}`)
	write(t, filepath.Join(home, ".openclaw", "skills", "gh-triage", "SKILL.md"), "---\nname: gh-triage\ndescription: Triage.\n---\n")
	write(t, filepath.Join(home, ".agents", "skills", "shared", "SKILL.md"), "---\nname: shared\ndescription: Shared.\n---\n")
	write(t, filepath.Join(home, ".codebuddy", "settings.json"), `{"hooks":{"PreToolUse":[{"matcher":".*","hooks":[{"type":"command","command":"/x/agentshield hook codebuddy"}]}]}}`)
	write(t, filepath.Join(home, ".trae", "skills", "style", "SKILL.md"), "---\nname: style\ndescription: Style.\n---\n")
	return home
}

func runInv(t *testing.T, home string) *Report {
	t.Helper()
	key, _ := signing.FromSeed(bytes.Repeat([]byte{4}, 32))
	rep, err := Run(Options{Home: home, Now: time.Date(2026, 9, 4, 8, 0, 0, 0, time.UTC), Version: "test", Key: key,
		HasAdmission: func(h string) (string, bool) { return "", false }})
	if err != nil {
		t.Fatal(err)
	}
	return rep
}

func byID(rep *Report) map[string]Candidate {
	out := map[string]Candidate{}
	for _, c := range rep.Candidates {
		out[c.CandidateID] = c
	}
	return out
}

func TestDiscoversPlatformsAndSkills(t *testing.T) {
	rep := runInv(t, fakeHome(t))
	if strings.Join(rep.Platforms, ",") != "hermes,openclaw,codebuddy,trae" {
		t.Fatalf("platforms %v", rep.Platforms)
	}
	c := byID(rep)
	for _, want := range []string{"platform:hermes", "platform:openclaw", "platform:codebuddy"} {
		if _, ok := c[want]; !ok {
			t.Fatalf("missing %s in %v", want, keys(c))
		}
	}
	skills := 0
	for id, cand := range c {
		if cand.SourceType == "skill_dir" {
			skills++
			if cand.Attributes["admission_verdict"] != "none" || len(cand.EvidenceIDs) != 1 || len(cand.ArtifactDigest) != 64 {
				t.Fatalf("skill candidate incomplete: %s %+v", id, cand)
			}
		}
	}
	if skills != 4 { // report-beautifier, gh-triage, shared, style (not-a-skill excluded)
		t.Fatalf("expected 4 skills, got %d: %v", skills, keys(c))
	}
	if c["platform:openclaw"].Attributes["agentshield_install_gate"] != "true" || c["platform:openclaw"].Attributes["agentshield_tool_hook"] != "true" {
		t.Fatalf("openclaw adapters not detected: %v", c["platform:openclaw"].Attributes)
	}
	if c["platform:codebuddy"].Attributes["agentshield_tool_hook"] != "true" {
		t.Fatal("codebuddy PreToolUse hook not detected")
	}
	if c["platform:hermes"].Attributes["agentshield_install_gate"] == "true" {
		t.Fatal("hermes has no install gate; must not be claimed")
	}
	facts := 0
	for _, f := range rep.Facts {
		if f.State != "observed" || f.Domain != "control_plane" {
			t.Fatalf("adapter facts must be observed control_plane: %+v", f)
		}
		facts++
	}
	if facts != 4 { // openclaw gate+hook, codebuddy hook, hermes plugin marker
		t.Fatalf("expected 4 observed facts, got %d", facts)
	}
}

func TestNeverLeaksSecretsOrHomePath(t *testing.T) {
	home := fakeHome(t)
	rep := runInv(t, home)
	raw, _ := json.Marshal(rep)
	if bytes.Contains(raw, []byte(secretMarker)) {
		t.Fatal("inventory output leaked a secret value")
	}
	if bytes.Contains(raw, []byte(home)) {
		t.Fatal("inventory output leaked the absolute home path")
	}
	for _, ev := range rep.Evidence {
		if ev.Signature == "" || len(ev.ContentHash) != 64 {
			t.Fatalf("evidence unsigned or unhashed: %+v", ev)
		}
	}
}

func TestEveryEvidenceReferencedAndEveryCandidateBacked(t *testing.T) {
	rep := runInv(t, fakeHome(t))
	ids := map[string]bool{}
	for _, ev := range rep.Evidence {
		ids[ev.EvidenceID] = true
	}
	referenced := map[string]bool{}
	for _, c := range rep.Candidates {
		if len(c.EvidenceIDs) == 0 {
			t.Fatalf("candidate without evidence: %s", c.CandidateID)
		}
		for _, id := range c.EvidenceIDs {
			if !ids[id] {
				t.Fatalf("dangling evidence ref %s", id)
			}
			referenced[id] = true
		}
	}
	for _, f := range rep.Facts {
		for _, id := range f.EvidenceIDs {
			referenced[id] = true
		}
	}
	if len(referenced) != len(ids) {
		t.Fatal("orphan evidence present")
	}
}

func TestProjectSkillDirsAndDedup(t *testing.T) {
	home := fakeHome(t)
	cwd := t.TempDir()
	write(t, filepath.Join(cwd, ".agents", "skills", "proj", "SKILL.md"), "---\nname: proj\ndescription: P.\n---\n")
	key, _ := signing.FromSeed(bytes.Repeat([]byte{4}, 32))
	rep, err := Run(Options{Home: home, Cwd: cwd, Version: "test", Key: key})
	if err != nil {
		t.Fatal(err)
	}
	seen := 0
	for _, c := range rep.Candidates {
		if c.Name == "proj" {
			seen++
		}
	}
	if seen != 1 {
		t.Fatalf("project skill discovered %d times (openclaw and trae both scan .agents/skills; must dedupe)", seen)
	}
}

func TestEmptyHomeYieldsEmptyReport(t *testing.T) {
	rep := runInv(t, t.TempDir())
	if len(rep.Platforms) != 0 || len(rep.Candidates) != 0 || len(rep.Evidence) != 0 {
		t.Fatalf("%+v", rep)
	}
}

func TestSampleIsCurrent(t *testing.T) {
	// deterministic: fixed key/time; home is redacted to "~" so temp paths do not leak into the sample
	rep := runInv(t, fakeHome(t))
	got, _ := json.MarshalIndent(rep, "", "  ")
	p := filepath.Join("..", "..", "testdata", "contracts", "inventory.sample.json")
	if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
		_ = os.WriteFile(p, append(got, '\n'), 0o644)
	}
	want, err := os.ReadFile(p)
	if err != nil {
		t.Fatalf("missing sample: %v", err)
	}
	if !bytes.Equal(bytes.TrimSpace(want), got) {
		t.Fatal("inventory sample drifted; regenerate with AGENTSHIELD_UPDATE_SAMPLES=1")
	}
}

func keys(m map[string]Candidate) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}
