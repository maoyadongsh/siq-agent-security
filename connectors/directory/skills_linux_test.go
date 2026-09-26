//go:build linux

package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func skillFixture(t *testing.T, root, name, content string) string {
	t.Helper()
	dir := filepath.Join(root, name)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "SKILL.md"), []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
	return dir
}

func skillPlan(roots ...string) protocol.ScanPlan {
	return protocol.ScanPlan{Scope: &protocol.Scope{Roots: roots, Include: []string{"SKILL.md"}}, Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20}}
}

func TestSkillCollectionIndependentIdentityAndNoExecution(t *testing.T) {
	root := t.TempDir()
	body := "---\nname: same-name\nallowed-tools: [read_file, terminal]\n---\n"
	marker := filepath.Join(root, "must-not-exist")
	first := skillFixture(t, root, "one", body+"$(touch "+marker+")\nsecret-body-not-uploaded")
	skillFixture(t, root, "two", body)
	if err := os.WriteFile(filepath.Join(first, ".env"), []byte("SECRET=never-read"), 0600); err != nil {
		t.Fatal(err)
	}
	got, err := collectSkills(skillPlan(root, first))
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Observations) != 2 || got.Truncated || len(got.Issues) != 0 {
		t.Fatalf("unexpected collection: %+v", got)
	}
	if got.Observations[0].LocatorSHA256 == got.Observations[1].LocatorSHA256 {
		t.Fatal("same-name locations merged")
	}
	for _, item := range got.Observations {
		if item.Name != "same-name" || item.ParseStatus != "parsed" || strings.Join(item.DeclaredTools, ",") != "read_file,terminal" {
			t.Fatal(item)
		}
	}
	raw, _ := json.Marshal(got)
	for _, secret := range []string{root, "secret-body", "SECRET", "touch"} {
		if strings.Contains(string(raw), secret) {
			t.Fatal("raw content or path disclosed")
		}
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("skill content executed")
	}
}

func TestSkillCollectionRefusesSymlinksAndFIFO(t *testing.T) {
	root, external := t.TempDir(), t.TempDir()
	outside := skillFixture(t, external, "outside", "---\nname: outside\n---\n")
	if err := os.Symlink(outside, filepath.Join(root, "linked-dir")); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"file-link", "fifo"} {
		if err := os.Mkdir(filepath.Join(root, name), 0700); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Symlink(filepath.Join(outside, "SKILL.md"), filepath.Join(root, "file-link", "SKILL.md")); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Mkfifo(filepath.Join(root, "fifo", "SKILL.md"), 0600); err != nil {
		t.Fatal(err)
	}
	got, err := collectSkills(skillPlan(root))
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Observations) != 0 || !got.Truncated || len(got.Issues) < 2 {
		t.Fatal(got)
	}
	// Symlink in an ancestor must not be followed even when the final root is real.
	if err := os.Symlink(external, filepath.Join(root, "parent-link")); err != nil {
		t.Fatal(err)
	}
	got, err = collectSkills(skillPlan(filepath.Join(root, "parent-link", "outside")))
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Observations) != 0 || !got.Truncated {
		t.Fatal("ancestor symlink followed")
	}
}

func TestSkillCollectionSizeAndParseFailures(t *testing.T) {
	root := t.TempDir()
	skillFixture(t, root, "oversize", strings.Repeat("x", protocol.MaxSkillManifestBytes+1))
	skillFixture(t, root, "invalid", "---\nname: sample\nallowed-tools: [$(run)]\n---\n")
	got, err := collectSkills(skillPlan(root))
	if err != nil {
		t.Fatal(err)
	}
	if !got.Truncated || len(got.Observations) != 1 || got.Observations[0].ParseStatus != "unsupported" || len(got.Observations[0].DeclaredTools) != 0 {
		t.Fatal(got)
	}
	plan := skillPlan(root)
	plan.Limits.MaxBytes = 1
	got, err = collectSkills(plan)
	if err != nil || !got.Truncated || len(got.Observations) != 0 {
		t.Fatal("partial digest emitted")
	}
}

func TestSkillCollectionScopeAndProtocol(t *testing.T) {
	root := t.TempDir()
	for _, plan := range []protocol.ScanPlan{{}, skillPlan("/"), skillPlan(root + "/*")} {
		if _, err := collectSkills(plan); err == nil {
			t.Fatal("unsafe scope accepted")
		}
	}
	if result := validateScopeOp(nil); result.Valid || len(result.Errors) == 0 {
		t.Fatal("invalid scope advertised as valid")
	}
	plan := skillPlan(root)
	plan.Scope.Include = []string{".env"}
	if _, err := collectSkills(plan); err == nil {
		t.Fatal("non-skill include accepted")
	}
	skillFixture(t, root, "sample", "---\nname: sample\n---\n")
	params, _ := json.Marshal(collectParams{Plan: skillPlan(root)})
	response := dispatch(&protocol.Request{ID: "fixture", Op: protocol.OpCollectSkills, Params: params})
	if !response.OK {
		t.Fatal(response)
	}
	got, ok := response.Result.(protocol.SkillCollection)
	if !ok || len(got.Observations) != 1 {
		t.Fatal(response)
	}
}

func TestSkillDirectoryHandleSurvivesPathReplacement(t *testing.T) {
	root, outside := t.TempDir(), t.TempDir()
	dir := skillFixture(t, root, "original", "original bytes")
	skillFixture(t, outside, "replacement", "outside bytes")
	opened, err := skillRoot(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer opened.Close()
	if err := os.Rename(dir, filepath.Join(root, "moved")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(outside, "replacement"), dir); err != nil {
		t.Fatal(err)
	}
	file, err := skillOpenAt(opened, "SKILL.md", false)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	buffer := make([]byte, 64)
	n, err := file.Read(buffer)
	if err != nil || string(buffer[:n]) != "original bytes" {
		t.Fatal("replaced path escaped descriptor anchor")
	}
}

func TestSkillCollectionFileLimit(t *testing.T) {
	root := t.TempDir()
	skillFixture(t, root, "a", "---\nname: a\n---\n")
	skillFixture(t, root, "b", "---\nname: b\n---\n")
	plan := skillPlan(root)
	plan.Limits.MaxFiles = 1
	got, err := collectSkills(plan)
	if err != nil || len(got.Observations) != 1 || !got.Truncated {
		t.Fatal(got, err)
	}
}
