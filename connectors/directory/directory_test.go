package main

// 受控目录 Connector 负向测试（contract §4）：
// 空范围拒绝（无默认范围）、manifest 发现、.env 不读取、符号链接逃逸跳过、限额截断。

import (
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestValidateScopeRejectsEmpty(t *testing.T) {
	// 受控目录 Connector 无默认范围：空 scope 必须拒绝（§10.1 显式授权）
	if errs := validateScope(nil); len(errs) == 0 {
		t.Fatal("nil scope accepted")
	}
	if errs := validateScope(&protocol.Scope{}); len(errs) == 0 {
		t.Fatal("empty roots accepted")
	}
}

func TestValidateScopeRejectsRoot(t *testing.T) {
	if errs := validateScope(&protocol.Scope{Roots: []string{"/"}}); len(errs) == 0 {
		t.Fatal("root path accepted")
	}
}

func TestCollectFindsManifests(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "legal-agent", "SOUL.md"), "我是法律审核助手")
	writeFile(t, filepath.Join(dir, "risk-agent", "agent.yaml"), "tools: [document.read]")
	writeFile(t, filepath.Join(dir, "not-an-agent", "readme.txt"), "普通文件")

	plan := protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: defaultLimits(),
	}
	batch, err := collectOp(plan)
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 2 {
		t.Fatalf("expected 2 candidates, got %d", len(batch.Candidates))
	}
	// SOUL.md → framework hermes
	for _, c := range batch.Candidates {
		if filepath.Base(c.SourceLocator) == "" && c.Framework == "" {
			t.Fatal("candidate missing fields")
		}
	}
	// 每条 evidence 必须有 candidate 引用（contract §4）
	ids := map[string]bool{}
	for _, c := range batch.Candidates {
		for _, e := range c.EvidenceIDs {
			ids[e] = true
		}
	}
	for _, ev := range batch.Evidence {
		if !ids[ev.EvidenceID] {
			t.Fatalf("orphan evidence: %s", ev.EvidenceID)
		}
	}
}

func TestCollectNeverReadsEnv(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "agent", "agent.yaml"), "ok")
	writeFile(t, filepath.Join(dir, "agent", ".env"), "SECRET=do-not-read")

	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: defaultLimits(),
	})
	if err != nil {
		t.Fatal(err)
	}
	for _, ev := range batch.Evidence {
		if ev.SourceLocator == ".env" || ev.ContentHash == protocol.ContentHash([]byte("SECRET=do-not-read")) {
			t.Fatal(".env content must never be read/hashed")
		}
	}
}

func TestCollectSkipsSymlinkEscape(t *testing.T) {
	dir := t.TempDir()
	outside := t.TempDir()
	writeFile(t, filepath.Join(outside, "agent.yaml"), "outside")
	if err := os.Symlink(outside, filepath.Join(dir, "evil-link")); err != nil {
		t.Skip("symlink not supported")
	}
	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: defaultLimits(),
	})
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range batch.Candidates {
		if c.SourceLocator == "directory://evil-link/agent.yaml" {
			t.Fatal("symlink escape candidate emitted")
		}
	}
}

func TestCollectTruncatesAtLimits(t *testing.T) {
	dir := t.TempDir()
	for i := 0; i < 30; i++ {
		writeFile(t, filepath.Join(dir, "agents", string(rune('a'+i%26))+string(rune('0'+i/26)), "agent.yaml"), "x")
	}
	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: protocol.CollectLimits{MaxFiles: 5, MaxBytes: 16 * 1024 * 1024},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) > 5 {
		t.Fatalf("limit exceeded: %d", len(batch.Candidates))
	}
	if !batch.Truncated {
		t.Fatal("expected truncated flag")
	}
}
