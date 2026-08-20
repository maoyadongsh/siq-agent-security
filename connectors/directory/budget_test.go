package main

// P1-6 字节预算测试（contract §4 补充）：
// 预算耗尽显式截断、禁止回退默认大小、被截断文件显式标注。

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestReadFileLimitedZeroBudget(t *testing.T) {
	// 剩余预算为 0/负数必须返回显式错误，禁止回退 1 MiB 继续读（P1-6）
	dir := t.TempDir()
	path := filepath.Join(dir, "agent.yaml")
	writeFile(t, path, strings.Repeat("x", 100))
	for _, budget := range []int64{0, -1} {
		if _, err := readFileLimited(path, budget); !errors.Is(err, errBudgetExhausted) {
			t.Fatalf("budget %d: expected errBudgetExhausted, got %v", budget, err)
		}
	}
	if data, err := readFileLimited(path, 10); err != nil || len(data) != 10 {
		t.Fatalf("budget 10: got len=%d err=%v", len(data), err)
	}
}

func TestCollectByteBudgetTruncates(t *testing.T) {
	// 总预算只够第一个文件的一部分：必须显式 truncated，且不得越预算多读
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "a-agent", "agent.yaml"), strings.Repeat("a", 64))
	writeFile(t, filepath.Join(dir, "b-agent", "agent.yaml"), strings.Repeat("b", 64))

	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: protocol.CollectLimits{MaxFiles: 10, MaxBytes: 32},
	})
	if err != nil {
		t.Fatal(err)
	}
	if !batch.Truncated {
		t.Fatal("expected truncated flag when byte budget exhausted")
	}
	// 第一个文件被预算截断读取：候选属性必须显式标注不完整（P1-6）
	if len(batch.Candidates) != 1 {
		t.Fatalf("expected 1 candidate, got %d", len(batch.Candidates))
	}
	attrs := batch.Candidates[0].Attributes
	if attrs["content_truncated"] != "true" {
		t.Fatalf("expected content_truncated=true, got %q", attrs["content_truncated"])
	}
	if attrs["bytes_read"] != "32" || attrs["bytes_limit"] != "32" {
		t.Fatalf("unexpected budget attributes: %v", attrs)
	}
}

func TestCollectByteBudgetExactFit(t *testing.T) {
	// 预算刚好够所有文件：不截断、不标注
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "a-agent", "agent.yaml"), strings.Repeat("a", 16))
	writeFile(t, filepath.Join(dir, "b-agent", "agent.yaml"), strings.Repeat("b", 16))

	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: protocol.CollectLimits{MaxFiles: 10, MaxBytes: 32},
	})
	if err != nil {
		t.Fatal(err)
	}
	if batch.Truncated {
		t.Fatal("exact-fit budget must not be marked truncated")
	}
	if len(batch.Candidates) != 2 {
		t.Fatalf("expected 2 candidates, got %d", len(batch.Candidates))
	}
	for _, c := range batch.Candidates {
		if c.Attributes["content_truncated"] != "false" {
			t.Fatalf("unexpected truncation mark: %v", c.Attributes)
		}
	}
}

// 防止回退行为复活：预算耗尽时第二个文件不得被读取（旧行为会回退 1 MiB 继续）。
func TestCollectNoFallbackReadBeyondBudget(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "a-agent", "agent.yaml"), strings.Repeat("a", 16))
	writeFile(t, filepath.Join(dir, "b-agent", "SOUL.md"), strings.Repeat("b", 16))

	batch, err := collectOp(protocol.ScanPlan{
		Scope:  &protocol.Scope{Roots: []string{dir}},
		Limits: protocol.CollectLimits{MaxFiles: 10, MaxBytes: 16},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 1 {
		t.Fatalf("budget exhausted must stop collection, got %d candidates", len(batch.Candidates))
	}
	if !batch.Truncated {
		t.Fatal("expected truncated flag")
	}
	if _, err := os.Stat(dir); err != nil {
		t.Fatal(err)
	}
}
