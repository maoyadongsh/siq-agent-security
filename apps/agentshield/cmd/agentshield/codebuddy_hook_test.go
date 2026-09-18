package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/state"
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
			if _, err := state.Open(dir); err != nil {
				t.Fatal(err)
			}
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

func TestWorkBuddyHookInvalidArgumentsStillDeny(t *testing.T) {
	for _, args := range [][]string{
		{"workbuddy", "--state-dir", "relative"},
		{"workbuddy", "--state-dir", t.TempDir(), "unexpected"},
		{"workbuddy", "--unknown"},
	} {
		t.Run(strings.Join(args[1:], "_"), func(t *testing.T) {
			oldIn, oldOut := os.Stdin, os.Stdout
			inR, inW, err := os.Pipe()
			if err != nil {
				t.Fatal(err)
			}
			outR, outW, err := os.Pipe()
			if err != nil {
				t.Fatal(err)
			}
			os.Stdin, os.Stdout = inR, outW
			go func() {
				_, _ = inW.Write([]byte(`{"hook_event_name":"PreToolUse","tool_name":"Read"}`))
				_ = inW.Close()
			}()
			hookErr := cmdHook(args)
			_ = outW.Close()
			os.Stdin, os.Stdout = oldIn, oldOut
			_ = inR.Close()
			if hookErr != nil {
				t.Fatal(hookErr)
			}
			var buf bytes.Buffer
			if _, err := buf.ReadFrom(outR); err != nil {
				t.Fatal(err)
			}
			_ = outR.Close()
			var response adapters.CodeBuddyOutput
			if err := json.Unmarshal(bytes.TrimSpace(buf.Bytes()), &response); err != nil {
				t.Fatal(err)
			}
			if response.HookSpecificOutput.PermissionDecision != "deny" || !strings.Contains(response.HookSpecificOutput.PermissionDecisionReason, "fail-closed") {
				t.Fatalf("invalid invocation did not deny: %s", buf.String())
			}
		})
	}
}

func TestWorkBuddyHookStateDirOverridesEnv(t *testing.T) {
	ambient := t.TempDir()
	selected := t.TempDir()
	if _, err := state.Open(ambient); err != nil {
		t.Fatal(err)
	}
	if _, err := state.Open(selected); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(ambient, "config.json"), []byte(`{"enforcement_mode":"warn"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(selected, "config.json"), []byte(`{"enforcement_mode":"block"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", ambient)
	oldIn, oldOut := os.Stdin, os.Stdout
	inR, inW, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	outR, outW, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	os.Stdin, os.Stdout = inR, outW
	go func() {
		_, _ = inW.Write([]byte(`{"hook_event_name":"PreToolUse","tool_name":"Read"}`))
		_ = inW.Close()
	}()
	hookErr := cmdHook([]string{"workbuddy", "--state-dir", selected})
	_ = outW.Close()
	os.Stdin, os.Stdout = oldIn, oldOut
	_ = inR.Close()
	if hookErr != nil {
		t.Fatal(hookErr)
	}
	var buf bytes.Buffer
	if _, err := buf.ReadFrom(outR); err != nil {
		t.Fatal(err)
	}
	_ = outR.Close()
	var response adapters.CodeBuddyOutput
	if err := json.Unmarshal(bytes.TrimSpace(buf.Bytes()), &response); err != nil {
		t.Fatal(err)
	}
	if response.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatalf("selected block state must deny: %s", buf.String())
	}
	raw, err := os.ReadFile(filepath.Join(selected, "pending", "decisions.jsonl"))
	if err != nil || !strings.Contains(string(raw), `"platform":"workbuddy"`) {
		t.Fatalf("pending: %v %s", err, raw)
	}
	if _, err := os.Stat(filepath.Join(ambient, "pending", "decisions.jsonl")); !os.IsNotExist(err) {
		t.Fatal("ambient state was used")
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
