package main

// OpenClaw Connector 测试：发现 + declared 权限事实 + 敏感文件永不读 + 空范围拒绝。

import (
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

const fixtureConfig = `{
  "agents": {
    "list": [
      {"id": "ic_legal_scanner", "name": "投研法务扫描员", "workspace": "/home/maoyd/workspace/legal", "model": "kimi/kimi-code"},
      {"id": "ic_risk_controller", "name": "投研风控员", "model": {"primary": "minimax/MiniMax-M3", "fallbacks": ["kimi/kimi-code"]}}
    ]
  }
}`

func TestValidateScopeRejectsEmpty(t *testing.T) {
	if errs := validateScope(nil); len(errs) == 0 {
		t.Fatal("nil scope accepted（OpenClaw 目录必须显式授权）")
	}
}

func TestCollectDiscoversAgentsAndDeclaredFacts(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "openclaw.json"), []byte(fixtureConfig), 0o644); err != nil {
		t.Fatal(err)
	}
	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: defaultLimits(),
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 2 {
		t.Fatalf("expected 2 agents, got %d", len(batch.Candidates))
	}
	// declared 权限事实：model + filesystem，state 必须为 declared（绝不 effective）
	modelFacts, fsFacts := 0, 0
	for _, pf := range batch.PermissionFacts {
		if pf.State != "declared" {
			t.Fatalf("connector 产出非 declared 状态: %s", pf.State)
		}
		if pf.Domain == "model" {
			modelFacts++
		}
		if pf.Domain == "filesystem" {
			fsFacts++
		}
	}
	// 2 个 model 事实（kimi/kimi-code、MiniMax-M3、kimi 回退 = 3）+ 1 个 workspace
	if modelFacts != 3 {
		t.Fatalf("model facts: got %d, want 3", modelFacts)
	}
	if fsFacts != 1 {
		t.Fatalf("filesystem facts: got %d, want 1", fsFacts)
	}
}

func TestCollectNeverReadsAuthProfiles(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "openclaw.json"), []byte(fixtureConfig), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(dir, "agents"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "agents", "auth-profiles.json"), []byte(`{"secret":"do-not-hash-this"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: defaultLimits(),
	})
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, ev := range batch.Evidence {
		if ev.SourceLocator == "agents/auth-profiles.json" {
			found = true
			// 内容永不哈希：只记大小
			want := "size:"
			if len(ev.ContentHash) < len(want) || ev.ContentHash[:len(want)] != want {
				t.Fatalf("auth-profiles 内容被哈希（%s），必须只记大小", ev.ContentHash)
			}
		}
		if ev.ContentHash == protocol.ContentHash([]byte(`{"secret":"do-not-hash-this"}`)) {
			t.Fatal("auth-profiles 内容哈希泄露")
		}
	}
	if !found {
		t.Fatal("auth-profiles secret_ref 证据缺失")
	}
}
