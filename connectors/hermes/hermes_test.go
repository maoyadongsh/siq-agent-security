package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestValidateScopeOp(t *testing.T) {
	dir := t.TempDir()
	if err := os.Mkdir(filepath.Join(dir, "profiles"), 0o755); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		name      string
		scope     *protocol.Scope
		wantValid bool
	}{
		{"nil scope", nil, false},
		{"empty scope", &protocol.Scope{}, false},
		{"filesystem root", &protocol.Scope{Roots: []string{"/"}}, false},
		{"env root", &protocol.Scope{Roots: []string{dir + "/.env-profiles"}}, false},
		{"secret root", &protocol.Scope{Roots: []string{dir + "/secret-stuff"}}, false},
		{"existing dir", &protocol.Scope{Roots: []string{dir}}, true},
		{"trailing glob", &protocol.Scope{Roots: []string{dir + "/*"}}, true},
		{"missing dir", &protocol.Scope{Roots: []string{dir + "/nope"}}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			vr := validateScopeOp(tc.scope)
			if vr.Valid != tc.wantValid {
				t.Fatalf("valid=%v want %v (errors=%v)", vr.Valid, tc.wantValid, vr.Errors)
			}
		})
	}
}

func TestExtractConfigFacts(t *testing.T) {
	yaml := `# hermes profile
model:
  default: gpt-4o
  temperature: 0.2
provider: openai
platform_toolsets:
  - name: siq_legal_advisor
  - name: mem0
memory: false
`
	model, provider, toolsets := extractConfigFacts([]byte(yaml))
	if model != "gpt-4o" {
		t.Errorf("model=%q want gpt-4o", model)
	}
	if provider != "openai" {
		t.Errorf("provider=%q want openai", provider)
	}
	wantToolsets := []string{"mem0", "siq_legal_advisor"}
	if len(toolsets) != len(wantToolsets) {
		t.Fatalf("toolsets=%v want %v", toolsets, wantToolsets)
	}
	for i := range wantToolsets {
		if toolsets[i] != wantToolsets[i] {
			t.Errorf("toolsets[%d]=%q want %q", i, toolsets[i], wantToolsets[i])
		}
	}
}

func TestCollectProfiles(t *testing.T) {
	root := t.TempDir()
	profilesDir := filepath.Join(root, "profiles")
	profileDir := filepath.Join(profilesDir, "siq_legal_advisor")
	if err := os.MkdirAll(profileDir, 0o755); err != nil {
		t.Fatal(err)
	}
	config := "model:\n  default: gpt-4o\nprovider: openai\nplatform_toolsets:\n  - name: siq_legal_advisor\n"
	if err := os.WriteFile(filepath.Join(profileDir, "config.yaml"), []byte(config), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(profileDir, "SOUL.md"), []byte("You are a legal advisor. Password: hunter2"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(profileDir, ".env"), []byte("OPENAI_API_KEY=sk-super-secret-value"), 0o600); err != nil {
		t.Fatal(err)
	}

	plan := protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{profilesDir + "/*"}, Include: []string{"config.yaml", "SOUL.md"}},
		Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20},
	}
	batch, err := collectOp(plan)
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 1 {
		t.Fatalf("candidates=%d want 1", len(batch.Candidates))
	}
	cand := batch.Candidates[0]
	if cand.Name != "siq_legal_advisor" {
		t.Errorf("candidate name=%q", cand.Name)
	}
	if cand.Framework != "hermes" || cand.SourceType != "hermes_profile" {
		t.Errorf("candidate framework=%q source_type=%q", cand.Framework, cand.SourceType)
	}
	if cand.Confidence != 1.0 {
		t.Errorf("confidence=%v want 1.0", cand.Confidence)
	}
	if cand.Attributes["model"] != "gpt-4o" {
		t.Errorf("attributes.model=%q", cand.Attributes["model"])
	}
	if !strings.Contains(cand.Attributes["toolsets"], "siq_legal_advisor") {
		t.Errorf("attributes.toolsets=%q", cand.Attributes["toolsets"])
	}

	if len(batch.Evidence) != 3 {
		t.Fatalf("evidence=%d want 3 (config.yaml, SOUL.md, .env)", len(batch.Evidence))
	}
	byID := make(map[string]*protocol.Evidence, len(batch.Evidence))
	for _, ev := range batch.Evidence {
		byID[ev.EvidenceID] = ev
	}
	envEv := byID["ev:hermes:siq_legal_advisor:.env"]
	if envEv == nil {
		t.Fatal("missing .env secret_ref evidence")
	}
	if envEv.Classification != "secret_ref" {
		t.Errorf(".env classification=%q want secret_ref", envEv.Classification)
	}
	if strings.Contains(envEv.SourceLocator, "sk-") || strings.Contains(envEv.SourceLocator, "OPENAI") {
		t.Errorf(".env content leaked into source_locator: %q", envEv.SourceLocator)
	}
	if envEv.ContentHash == "" {
		t.Error(".env evidence missing content_hash")
	}
	if len(cand.EvidenceIDs) != 3 {
		t.Errorf("candidate evidence_ids=%v want 3 references", cand.EvidenceIDs)
	}
	if !strings.HasPrefix(batch.Cursor, "hermes-cursor:") {
		t.Errorf("cursor=%q", batch.Cursor)
	}
	// every evidence must be referenced by the candidate (contract hard req 4)
	kept, dropped, err := ValidateBatchReferencesLocal(batch.Candidates, batch.Evidence)
	if err != nil {
		t.Fatal(err)
	}
	if len(kept) != 3 || len(dropped) != 0 {
		t.Errorf("batch references: kept=%d dropped=%d", len(kept), len(dropped))
	}
}

// ValidateBatchReferencesLocal is a local copy of the Edge-side rule used to
// assert batch validity in this test (the Edge enforces the real one).
func ValidateBatchReferencesLocal(cands []*protocol.Candidate, evs []*protocol.Evidence) (kept, dropped []*protocol.Evidence, err error) {
	referenced := make(map[string]bool)
	for _, c := range cands {
		for _, id := range c.EvidenceIDs {
			referenced[id] = true
		}
	}
	for _, ev := range evs {
		if referenced[ev.EvidenceID] {
			kept = append(kept, ev)
		} else {
			dropped = append(dropped, ev)
		}
	}
	return kept, dropped, nil
}

func TestCollectSymlinkEscape(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	if err := os.WriteFile(filepath.Join(outside, "config.yaml"), []byte("model:\n  default: gpt-4o\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	profiles := filepath.Join(root, "profiles")
	if err := os.MkdirAll(profiles, 0o755); err != nil {
		t.Fatal(err)
	}
	// Contract §4 negative test: a symlink inside the scope pointing outside.
	if err := os.Symlink(outside, filepath.Join(profiles, "evil")); err != nil {
		t.Skipf("cannot create symlink: %v", err)
	}
	plan := protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{profiles + "/*"}, Include: []string{"config.yaml"}},
		Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20},
	}
	batch, err := collectOp(plan)
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 0 {
		t.Errorf("symlink escape must be skipped, got %d candidates", len(batch.Candidates))
	}
}

func TestCollectTruncation(t *testing.T) {
	root := t.TempDir()
	for i := 0; i < 3; i++ {
		p := filepath.Join(root, fmt.Sprintf("p%d", i))
		if err := os.MkdirAll(p, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(p, "config.yaml"), []byte("model:\n  default: m1\n"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	plan := protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{root + "/*"}, Include: []string{"config.yaml"}},
		Limits: protocol.CollectLimits{MaxFiles: 2, MaxBytes: 1 << 20},
	}
	batch, err := collectOp(plan)
	if err != nil {
		t.Fatal(err)
	}
	if !batch.Truncated {
		t.Error("expected truncated=true when profile limit is hit")
	}
	if len(batch.Candidates) != 2 {
		t.Errorf("candidates=%d want 2", len(batch.Candidates))
	}
}

func TestEnvOnlyProfileHasNoOrphanEvidence(t *testing.T) {
	root := t.TempDir()
	profileDir := filepath.Join(root, "profiles", "bare")
	if err := os.MkdirAll(profileDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(profileDir, ".env"), []byte("KEY=value"), 0o600); err != nil {
		t.Fatal(err)
	}
	plan := protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{filepath.Join(root, "profiles") + "/*"}, Include: []string{"config.yaml", "SOUL.md"}},
		Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20},
	}
	batch, err := collectOp(plan)
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 0 || len(batch.Evidence) != 0 {
		t.Errorf("profile without config.yaml/SOUL.md must produce nothing (candidates=%d evidence=%d)", len(batch.Candidates), len(batch.Evidence))
	}
}

func TestExtractConfigFactsRecognizesPlainToolsets(t *testing.T) {
	// 本机真实 profile 使用 toolsets:（非 platform_toolsets:）——必须识别
	content := "model:\n  default: Qwen3.6-35B-A3B-FP8\nproviders: {}\ntoolsets:\n  - terminal\n  - file\n  - code_execution\n"
	model, _, toolsets := extractConfigFacts([]byte(content))
	if model != "Qwen3.6-35B-A3B-FP8" {
		t.Fatalf("model 未解析: %q", model)
	}
	if len(toolsets) != 3 {
		t.Fatalf("toolsets 未解析（got %v），plain toolsets: 键必须识别", toolsets)
	}
}
