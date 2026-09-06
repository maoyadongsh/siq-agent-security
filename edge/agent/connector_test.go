package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

// TestValidateScopeSafety covers the hermes scope validation rules (empty
// scope, filesystem root, ".env"/"secret" roots, ambiguous wildcards,
// relative paths, missing roots) — the same code path the hermes connector's
// validate_scope op runs.
func TestValidateScopeSafety(t *testing.T) {
	cases := []struct {
		name  string
		scope *protocol.Scope
	}{
		{"nil scope", nil},
		{"no roots", &protocol.Scope{}},
		{"filesystem root", &protocol.Scope{Roots: []string{"/"}}},
		{"env root", &protocol.Scope{Roots: []string{"/tmp/.env-profiles"}}},
		{"secret root", &protocol.Scope{Roots: []string{"/tmp/secret-stuff"}}},
		{"midpath wildcard", &protocol.Scope{Roots: []string{"/tmp/a/*/b"}}},
		{"recursive wildcard", &protocol.Scope{Roots: []string{"/tmp/**"}}},
		{"question mark", &protocol.Scope{Roots: []string{"/tmp/profiles?"}}},
		{"relative root", &protocol.Scope{Roots: []string{"profiles"}}},
		{"missing root", &protocol.Scope{Roots: []string{"/nonexistent-siq-xyz"}}},
		{"glob with no matches", &protocol.Scope{Roots: []string{"/nonexistent-siq-xyz/*"}}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if err := protocol.ValidateScopeSafety(tc.scope); err == nil {
				t.Fatalf("expected rejection, got nil")
			}
		})
	}
}

func TestValidateScopeSafetyAcceptsValid(t *testing.T) {
	dir := t.TempDir()
	sub := filepath.Join(dir, "profiles")
	if err := os.Mkdir(sub, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := protocol.ValidateScopeSafety(&protocol.Scope{Roots: []string{sub}}); err != nil {
		t.Errorf("plain dir root: %v", err)
	}
	if err := protocol.ValidateScopeSafety(&protocol.Scope{Roots: []string{dir + "/*"}}); err != nil {
		t.Errorf("trailing glob root: %v", err)
	}
}

// TestValidateScopeSafetyRejectsSymlinkRoot: DEV10 / M-E2 — a scope root (or
// trailing-/* match) that is a symlink must be refused even when the target
// is an existing directory (Stat would have accepted it).
func TestValidateScopeSafetyRejectsSymlinkRoot(t *testing.T) {
	dir := t.TempDir()
	real := filepath.Join(dir, "real")
	if err := os.Mkdir(real, 0o755); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "link-root")
	if err := os.Symlink(real, link); err != nil {
		t.Skipf("symlink: %v", err)
	}
	if err := protocol.ValidateScopeSafety(&protocol.Scope{Roots: []string{link}}); err == nil {
		t.Fatal("symlink scope root must be rejected")
	} else if !strings.Contains(err.Error(), "symlink") {
		t.Fatalf("error should mention symlink, got %v", err)
	}

	// Glob parent/* where the only match is a symlink dir.
	parent := filepath.Join(dir, "glob-parent")
	if err := os.Mkdir(parent, 0o755); err != nil {
		t.Fatal(err)
	}
	childLink := filepath.Join(parent, "profiles")
	if err := os.Symlink(real, childLink); err != nil {
		t.Fatal(err)
	}
	if err := protocol.ValidateScopeSafety(&protocol.Scope{Roots: []string{parent + "/*"}}); err == nil {
		t.Fatal("trailing glob matching only symlink dirs must be rejected")
	}
}

func TestResolveConnectorBinRejectsUntrustedNames(t *testing.T) {
	for _, name := range []string{"/tmp/evil", "../evil", "bash", "hermes/../../evil", ""} {
		if _, err := ResolveConnectorBin(name, ""); err == nil {
			t.Fatalf("ResolveConnectorBin(%q) accepted an untrusted connector name", name)
		}
	}
}

// TestOfficialConnectorAllowlist：P1-4 新发现源必须在白名单内
// （找不到二进制是 "not found"，不得是 "not allowlisted"）。
func TestOfficialConnectorAllowlist(t *testing.T) {
	official := []string{
		"hermes", "openclaw", "docker", "directory",
		"systemd", "kubernetes", "process", "mcp",
		"piagent", "workbuddy", "dify",
	}
	for _, name := range official {
		_, err := ResolveConnectorBin(name, "")
		if err == nil {
			continue // 二进制恰好存在也算通过白名单
		}
		if got := err.Error(); !strings.Contains(got, "not found") {
			t.Fatalf("official connector %q rejected: %v", name, err)
		}
	}
}

// TestErrorCodeMapping verifies the connector error-code → typed error map
// (contract §3).
func TestErrorCodeMapping(t *testing.T) {
	for code, want := range map[string]error{
		protocol.CodeScopeInvalid:     ErrScopeInvalid,
		protocol.CodeLimitExceeded:    ErrLimitExceeded,
		protocol.CodeRedactionFailure: ErrRedactionFailure,
		protocol.CodeTimeout:          ErrTimeout,
		protocol.CodeUnsupported:      ErrUnsupported,
	} {
		got := mapCodeToError(code)
		if !errors.Is(got, want) {
			t.Errorf("mapCodeToError(%q)=%v, want %v", code, got, want)
		}
	}
	if err := mapCodeToError("unknown-code"); err == nil {
		t.Error("unknown code must produce an error")
	}
	if codeOf(ErrScopeInvalid) != protocol.CodeScopeInvalid {
		t.Errorf("codeOf(ErrScopeInvalid)=%q", codeOf(ErrScopeInvalid))
	}
	if codeOf(ErrOutputLimit) != protocol.CodeLimitExceeded {
		t.Errorf("codeOf(ErrOutputLimit)=%q", codeOf(ErrOutputLimit))
	}
	if codeOf(errors.New("boom")) != "internal_error" {
		t.Errorf("codeOf(generic)=%q", codeOf(errors.New("boom")))
	}
}

// TestPerOpDeadlineKillsHungConnector：父进程必须独立强制 per-op 超时（M-E1），
// 不能只靠传给子进程的环境变量。挂起 Connector 须在 Timeout 内返回 ErrTimeout，
// 并关闭连接以便后续任务继续。
func TestPerOpDeadlineKillsHungConnector(t *testing.T) {
	dir := t.TempDir()
	bin := filepath.Join(dir, "hang-connector")
	script := "#!/bin/sh\n# hang in-process (exec) so Kill reaps the sleeper; never emit NDJSON\nIFS= read -r _ || exit 0\nexec sleep 3600\n"
	if err := os.WriteFile(bin, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	c, err := NewSubprocessConnector(ctx, bin, SubprocessOptions{
		Name:    "hang",
		Timeout: 250 * time.Millisecond,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()

	start := time.Now()
	_, err = c.Describe(ctx)
	elapsed := time.Since(start)
	if !errors.Is(err, ErrTimeout) {
		t.Fatalf("hung connector must time out, got %v", err)
	}
	if elapsed > 3*time.Second {
		t.Fatalf("parent deadline too slow: %s (must not wait on child sleep)", elapsed)
	}

	_, err = c.Health(ctx)
	if !errors.Is(err, ErrConnectorClosed) {
		t.Fatalf("after timeout connector must be closed, got %v", err)
	}
}

// TestRequestResponseEnvelope verifies the NDJSON request/response wire shape.
func TestRequestResponseEnvelope(t *testing.T) {
	req := protocol.Request{ID: "req-000001", Op: protocol.OpCollect, Params: json.RawMessage(`{"plan":{}}`)}
	data, err := json.Marshal(&req)
	if err != nil {
		t.Fatal(err)
	}
	var back protocol.Request
	if err := json.Unmarshal(data, &back); err != nil {
		t.Fatal(err)
	}
	if back.ID != req.ID || back.Op != req.Op || string(back.Params) != string(req.Params) {
		t.Errorf("request round trip mismatch: %s", data)
	}

	resp := protocol.Response{ID: req.ID, OK: false, Error: &protocol.ProtocolError{Code: protocol.CodeScopeInvalid, Message: "empty scope"}}
	data, err = json.Marshal(&resp)
	if err != nil {
		t.Fatal(err)
	}
	var backResp protocol.Response
	if err := json.Unmarshal(data, &backResp); err != nil {
		t.Fatal(err)
	}
	if backResp.OK || backResp.Error == nil || backResp.Error.Code != protocol.CodeScopeInvalid {
		t.Errorf("error response round trip mismatch: %s", data)
	}
}
