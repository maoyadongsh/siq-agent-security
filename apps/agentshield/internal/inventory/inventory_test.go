package inventory

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
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
	write(t, filepath.Join(home, ".hermes", "config.yaml"), "model: x\nplugins:\n  - agentshield\nplatform_toolsets:\n  - web\nplatform_toolset_modes:\n  web: allow\n")
	write(t, filepath.Join(home, ".hermes", "profiles", "work", "config.yaml"), "model:\n  default: local\ntoolsets:\n  - terminal\n  - web\n")
	write(t, filepath.Join(home, ".hermes", "profiles", "home", "SOUL.md"), "# home profile\n")
	write(t, filepath.Join(home, ".hermes", ".env"), "OPENAI_API_KEY="+secretMarker+"\n")
	write(t, filepath.Join(home, ".hermes", "skills", "report-beautifier", "SKILL.md"), "---\nname: report-beautifier\ndescription: Beautify.\nallowed-tools: terminal\n---\n# x\n")
	write(t, filepath.Join(home, ".hermes", "skills", "report-beautifier", "scripts", "run.sh"), "echo "+secretMarker+"\n")
	write(t, filepath.Join(home, ".hermes", "skills", "not-a-skill", "README.md"), "no SKILL.md here\n")
	write(t, filepath.Join(home, ".openclaw", "openclaw.json"), `{"security":{"installPolicy":{"enabled":true,"exec":{"command":"/usr/local/bin/agentshield","args":["policy-exec"]}}},"plugins":{"entries":{"agentshield":{"enabled":true}}},"agents":{"list":[{"id":"main","name":"Main"},{"id":"other","name":"Other"}]},"apiKey":"`+secretMarker+`"}`)
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
	if strings.Join(rep.Platforms, ",") != "codebuddy,hermes,openclaw,trae" {
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
	factsObs := 0
	declaredTools := 0
	for _, f := range rep.Facts {
		if f.State == "effective" {
			t.Fatalf("inventory must not claim effective: %+v", f)
		}
		if f.State == "observed" {
			if f.Domain != "control_plane" {
				t.Fatalf("adapter facts must be observed control_plane: %+v", f)
			}
			factsObs++
		}
		if f.State == "declared" && f.Domain == "tool" {
			declaredTools++
		}
	}
	if factsObs != 4 { // openclaw gate+hook, codebuddy hook, hermes plugin marker
		t.Fatalf("expected 4 observed facts, got %d", factsObs)
	}
	if declaredTools < 1 {
		t.Fatal("hermes platform_toolsets must produce declared tool facts")
	}
	profiles, agents := 0, 0
	for _, cand := range c {
		switch cand.SourceType {
		case "hermes_profile":
			profiles++
		case "openclaw_agent":
			agents++
		}
	}
	if profiles < 2 {
		t.Fatalf("expected >=2 hermes profiles, got %d: %v", profiles, keys(c))
	}
	if agents < 2 {
		t.Fatalf("expected >=2 openclaw agents, got %d: %v", agents, keys(c))
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

func writeExec(t *testing.T, path, content string) {
	t.Helper()
	_ = os.MkdirAll(filepath.Dir(path), 0o700)
	if err := os.WriteFile(path, []byte(content), 0o755); err != nil {
		t.Fatal(err)
	}
}

func requirePython3(t *testing.T) {
	t.Helper()
	if _, err := exec.LookPath("python3"); err != nil {
		t.Skip("python3 required for connector exec tests")
	}
}

func TestConnectorsMergeWithoutDroppingNative(t *testing.T) {
	requirePython3(t)
	home := fakeHome(t)
	native := runInv(t, home)
	if _, ok := byID(native)["platform:hermes"]; !ok {
		t.Fatal("need native hermes")
	}
	dir := t.TempDir()
	writeExec(t, filepath.Join(dir, "hermes", "hermes"), connectorScript(false, true))
	key, _ := signing.FromSeed(bytes.Repeat([]byte{4}, 32))
	rep, err := Run(Options{Home: home, Now: time.Date(2026, 9, 4, 8, 0, 0, 0, time.UTC), Version: "test", Key: key,
		ConnectorsDir: dir, HasAdmission: func(h string) (string, bool) { return "", false }})
	if err != nil {
		t.Fatal(err)
	}
	c := byID(rep)
	if _, ok := c["platform:hermes"]; !ok {
		t.Fatalf("native dropped: %v", keys(c))
	}
	if _, ok := c["connector:extra"]; !ok {
		t.Fatalf("connector candidate missing, skipped=%v ids=%v", rep.Skipped, keys(c))
	}
	for _, f := range rep.Facts {
		if f.State == "effective" || f.Resource.Value == "should-not-appear-effective" {
			t.Fatalf("effective fact leaked: %+v", f)
		}
	}
	var declared bool
	for _, f := range rep.Facts {
		if f.Resource.Value == "connector-declared-tool" && f.State == "declared" {
			declared = true
		}
	}
	if !declared {
		t.Fatalf("declared connector fact missing: %+v", rep.Facts)
	}
}

func TestConnectorsNetworkAccessSkipped(t *testing.T) {
	requirePython3(t)
	home := fakeHome(t)
	dir := t.TempDir()
	writeExec(t, filepath.Join(dir, "hermes", "hermes"), connectorScript(true, false))
	key, _ := signing.FromSeed(bytes.Repeat([]byte{4}, 32))
	rep, err := Run(Options{Home: home, Now: time.Date(2026, 9, 4, 8, 0, 0, 0, time.UTC), Version: "test", Key: key,
		ConnectorsDir: dir, HasAdmission: func(h string) (string, bool) { return "", false }})
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := byID(rep)["platform:hermes"]; !ok {
		t.Fatal("native dropped on connector skip")
	}
	if _, ok := byID(rep)["connector:extra"]; ok {
		t.Fatal("network_access connector must not merge")
	}
	joined := strings.Join(rep.Skipped, ",")
	if !strings.Contains(joined, "connector_failed:hermes") {
		t.Fatalf("skipped %v", rep.Skipped)
	}
}

func TestConnectorsDirUnreadable(t *testing.T) {
	home := fakeHome(t)
	key, _ := signing.FromSeed(bytes.Repeat([]byte{4}, 32))
	rep, err := Run(Options{Home: home, Now: time.Date(2026, 9, 4, 8, 0, 0, 0, time.UTC), Version: "test", Key: key,
		ConnectorsDir: filepath.Join(home, "no-such-connectors"), HasAdmission: func(h string) (string, bool) { return "", false }})
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := byID(rep)["platform:hermes"]; !ok {
		t.Fatal("native dropped")
	}
	if !strings.Contains(strings.Join(rep.Skipped, ","), "connectors_dir_unreadable") {
		t.Fatalf("skipped %v", rep.Skipped)
	}
}

func connectorScript(network, withCollect bool) string {
	net := "False"
	if network {
		net = "True"
	}
	collect := "False"
	if withCollect {
		collect = "True"
	}
	return `#!/usr/bin/env python3
import json, sys
NET = ` + net + `
COLLECT = ` + collect + `
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    if req.get("op") == "describe":
        print(json.dumps({"id": req.get("id"), "ok": True, "result": {
            "version": "0.0.1", "objects": ["hermes_profile"], "required_permissions": [],
            "data_categories": [], "max_output_bytes": 1024, "network_access": NET
        }}))
    elif req.get("op") == "collect" and COLLECT:
        print(json.dumps({"id": req.get("id"), "ok": True, "result": {
            "candidates": [{
                "candidate_id": "connector:extra", "source_type": "hermes_profile",
                "source_locator": "hermes://extra", "discovered_at": "2026-09-05T00:00:00Z",
                "name": "extra", "framework": "hermes", "evidence_ids": ["ev-conn-1"],
                "confidence": 1.0, "status": "candidate"
            }],
            "evidence": [{
                "evidence_id": "ev-conn-1", "source_type": "platform_config",
                "source_locator": "hermes://extra", "observed_at": "2026-09-05T00:00:00Z",
                "collected_at": "2026-09-05T00:00:00Z", "collector_id": "connector",
                "connector_version": "0.0.1", "content_hash": "ab"*32,
                "redaction_profile": "siq.redaction.v1", "classification": "internal",
                "signature": "f"*128
            }],
            "permission_facts": [
                {"subject": {"type": "agent_instance", "id": "extra"}, "domain": "tool",
                 "action": "invoke", "resource": {"type": "tool", "value": "should-not-appear-effective"},
                 "effect": "allow", "state": "effective", "authority": "connector", "evidence_ids": ["ev-conn-1"]},
                {"subject": {"type": "agent_instance", "id": "extra"}, "domain": "tool",
                 "action": "invoke", "resource": {"type": "tool", "value": "connector-declared-tool"},
                 "effect": "allow", "state": "declared", "authority": "connector", "evidence_ids": ["ev-conn-1"]}
            ]
        }}))
    sys.stdout.flush()
`
}
