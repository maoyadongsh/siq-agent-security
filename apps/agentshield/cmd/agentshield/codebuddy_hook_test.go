package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/adapters"
)

func TestCodeBuddyBootstrapFailuresStillProduceHookDecision(t *testing.T) {
	for _, tc := range []struct{ name, config, token, want string }{
		{"malformed", `{"enforcement_mode":"warn",invalid`, "short", "deny"},
		{"invalid-port", `{"enforcement_mode":"audit_only","port":-1}`, "short", "deny"},
		{"short-token", `{"enforcement_mode":"block"}`, "short", "deny"},
		{"missing-token", `{"enforcement_mode":"block"}`, "missing", "deny"},
		{"token-directory", `{"enforcement_mode":"block"}`, "directory", "deny"},
		{"warn", `{"enforcement_mode":"warn"}`, "short", "allow"},
		{"audit", `{"enforcement_mode":"audit_only"}`, "short", "allow"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
			if err := os.WriteFile(filepath.Join(dir, "config.json"), []byte(tc.config), 0o600); err != nil {
				t.Fatal(err)
			}
			tokenPath := filepath.Join(dir, "token")
			if tc.token == "directory" {
				if err := os.Mkdir(tokenPath, 0o700); err != nil {
					t.Fatal(err)
				}
			} else if tc.token != "missing" {
				if err := os.WriteFile(tokenPath, []byte("synthetic-private-canary"), 0o600); err != nil {
					t.Fatal(err)
				}
			}
			var buf bytes.Buffer
			input := `{"session_id":"fixture","tool_use_id":"fixture-call","hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"/fixture"}}`
			if err := runCodeBuddyHook(strings.NewReader(input), &buf); err != nil {
				t.Fatalf("must not exit with a non-blocking error: %v", err)
			}
			var out adapters.CodeBuddyOutput
			if err := json.Unmarshal(buf.Bytes(), &out); err != nil {
				t.Fatal(err)
			}
			if out.HookSpecificOutput.PermissionDecision != tc.want {
				t.Fatalf("decision=%s", out.HookSpecificOutput.PermissionDecision)
			}
			if strings.Contains(buf.String(), dir) || strings.Contains(buf.String(), "synthetic-private-canary") {
				t.Fatal("bootstrap output leaked diagnostics")
			}
			pending := filepath.Join(dir, "pending", "decisions.jsonl")
			original, err := os.ReadFile(pending)
			if err != nil {
				t.Fatal(err)
			}
			var record map[string]any
			if err := json.Unmarshal(bytes.TrimSpace(original), &record); err != nil {
				t.Fatal(err)
			}
			if record["outcome"] != tc.want || record["signed"] != false {
				t.Fatal("pending outcome incorrect")
			}
			buf.Reset()
			if err := runCodeBuddyHook(strings.NewReader(`{"hook_event_name":"PostToolUse","tool_name":"Read"}`), &buf); err != nil {
				t.Fatal(err)
			}
			var post adapters.CodeBuddyOutput
			if err := json.Unmarshal(buf.Bytes(), &post); err != nil {
				t.Fatal(err)
			}
			if post.HookSpecificOutput.PermissionDecision != "" || post.HookSpecificOutput.HookEventName != "PostToolUse" {
				t.Fatal("post must remain observation-only")
			}
			after, err := os.ReadFile(pending)
			if err != nil || !bytes.Equal(after, original) {
				t.Fatal("unavailable post fabricated a decision")
			}
			if tc.token == "missing" {
				if _, err := os.Stat(tokenPath); !os.IsNotExist(err) {
					t.Fatal("hook minted missing credential")
				}
			}
		})
	}
}

func TestCodeBuddyUnavailableStateStillBlocks(t *testing.T) {
	file := filepath.Join(t.TempDir(), "not-a-directory")
	if err := os.WriteFile(file, []byte("fixture"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", file)
	var out bytes.Buffer
	if err := runCodeBuddyHook(strings.NewReader(`{"hook_event_name":"PreToolUse","tool_name":"Read"}`), &out); err != nil {
		t.Fatal(err)
	}
	var response adapters.CodeBuddyOutput
	if err := json.Unmarshal(out.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	if response.HookSpecificOutput.PermissionDecision != "deny" || !strings.Contains(response.HookSpecificOutput.PermissionDecisionReason, "fail-closed") {
		t.Fatal("unusable state must block")
	}
}
