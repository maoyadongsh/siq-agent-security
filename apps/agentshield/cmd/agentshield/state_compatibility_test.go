package main

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"siq-agent-security/apps/agentshield/internal/state"
	"strings"
	"testing"
)

func TestCompatibilityCLIHelper(t *testing.T) {
	if os.Getenv("SIQ_COMPAT_CLI_HELPER") != "1" {
		return
	}
	for i, arg := range os.Args {
		if arg == "--" {
			os.Args = append([]string{"siq-agent-security"}, os.Args[i+1:]...)
			main()
			os.Exit(0)
		}
	}
	os.Exit(99)
}
func TestCLIIncompatibleStateNoSideEffects(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	marker := state.StateFormatMarker{Schema: state.StateFormatSchema, ProgramVersion: "fixture", FormatVersion: 999, PublishedAt: "2026-09-13T09:00:00Z"}
	raw, _ := json.Marshal(marker)
	if err := os.WriteFile(filepath.Join(dir, state.StateFormatMarkerName), raw, 0600); err != nil {
		t.Fatal(err)
	}
	commands := []string{"init", "serve", "start", "setup", "teardown", "admit", "import-skill", "inventory", "policy-exec", "pubkey", "verify", "export", "sync", "grant", "adapter", "openshell", "incomplete", "client-stage", "client-install", "client-upgrade-check", "service-upgrade", "service-rollback", "service-prepare", "service-register", "service-start", "service-stop", "service-unregister", "service-login", "launch-agent-prepare", "launch-agent-register", "launch-agent-load", "launch-agent-start", "launch-agent-stop", "launch-agent-unregister", "task-prepare", "task-register", "task-start", "task-stop", "task-unregister", "stop", "stop-request", "pair"}
	for _, command := range commands {
		t.Run(command, func(t *testing.T) {
			cmd := exec.Command(os.Args[0], "-test.run=^TestCompatibilityCLIHelper$", "--", command)
			cmd.Env = append(os.Environ(), "SIQ_COMPAT_CLI_HELPER=1")
			out, err := cmd.CombinedOutput()
			if err == nil || !strings.Contains(string(out), state.ErrIncompatibleState.Error()) {
				t.Fatalf("guard not reached: %s %v", out, err)
			}
			entries, err := os.ReadDir(dir)
			if err != nil || len(entries) != 1 {
				t.Fatal("CLI created files", err)
			}
			after, err := os.ReadFile(filepath.Join(dir, state.StateFormatMarkerName))
			if err != nil || !reflect.DeepEqual(raw, after) {
				t.Fatal("CLI changed marker")
			}
		})
	}
}
func TestExplicitServeChecksSelectedDirectoryOnly(t *testing.T) {
	ambient := t.TempDir()
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", ambient)
	_ = os.WriteFile(filepath.Join(ambient, state.StateFormatMarkerName), []byte("corrupt"), 0600)
	selected := t.TempDir()
	if err := cmdServe([]string{"--state-dir", selected}); err == nil || !strings.Contains(err.Error(), "configuration missing") {
		t.Fatalf("wrong selected state: %v", err)
	}
}

func TestCLIIncompatibleHookEmitsBlockingDecision(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	raw := []byte(`{"schema":"state-format/v1","program_version":"test","format_version":999,"published_at":"2026-09-13T09:00:00Z"}`)
	if err := os.WriteFile(filepath.Join(dir, state.StateFormatMarkerName), raw, 0600); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(os.Args[0], "-test.run=^TestCompatibilityCLIHelper$", "--", "hook", "workbuddy")
	cmd.Env = append(os.Environ(), "SIQ_COMPAT_CLI_HELPER=1")
	cmd.Stdin = strings.NewReader(`{"hook_event_name":"PreToolUse","tool_name":"Read"}`)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("non-blocking hook exit: %v %s", err, out)
	}
	var result struct {
		HookSpecificOutput struct {
			PermissionDecision string `json:"permissionDecision"`
		} `json:"hookSpecificOutput"`
	}
	if json.Unmarshal(out, &result) != nil || result.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatalf("no structured deny: %s", out)
	}
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != 1 {
		t.Fatal("hook wrote incompatible state", err)
	}
}
