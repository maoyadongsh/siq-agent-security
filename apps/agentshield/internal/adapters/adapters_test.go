package adapters

import (
	"bytes"
	"errors"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func deps(t *testing.T) PolicyExecDeps {
	t.Helper()
	pack, _ := rulepack.Builtin()
	key, _ := signing.FromSeed(bytes.Repeat([]byte{8}, 32))
	return PolicyExecDeps{Pack: pack, Key: key, Version: "test"}
}

func fixture(rel string) string {
	p, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", rel))
	return p
}

func TestPolicyExecBlocksQuarantineWarnsConditionsAllowsClean(t *testing.T) {
	cases := map[string]string{
		"malicious/env-webhook": "block",
		"benign/official-like":  "warn",
		"benign/pure-doc":       "allow",
	}
	for rel, want := range cases {
		in := `{"targetType":"skill","target":{"name":"x"},"source":{"kind":"clawhub","locator":"clawhub:x"},"stagedPath":"` + fixture(rel) + `"}`
		out := PolicyExec(strings.NewReader(in), deps(t))
		if out.Decision != want {
			t.Fatalf("%s: got %s (%s)", rel, out.Decision, out.Reason)
		}
		if out.AdmissionID == "" || out.Verdict == "" {
			t.Fatalf("%s: response must carry admission id and verdict", rel)
		}
	}
}

func TestPolicyExecFailsClosed(t *testing.T) {
	for name, in := range map[string]string{
		"malformed":    `{not json`,
		"no path":      `{"targetType":"skill"}`,
		"missing dir":  `{"targetType":"skill","stagedPath":"/nonexistent/skill"}`,
		"file not dir": `{"targetType":"skill","stagedPath":"` + fixture("benign/pure-doc/SKILL.md") + `"}`,
	} {
		if out := PolicyExec(strings.NewReader(in), deps(t)); out.Decision != "block" {
			t.Fatalf("%s: must block, got %s", name, out.Decision)
		}
	}
	if out := PolicyExec(strings.NewReader(`{"targetType":"plugin","stagedPath":"/x"}`), deps(t)); out.Decision != "warn" {
		t.Fatalf("plugin targets are out of scope and must warn, got %s", out.Decision)
	}
}

type fakeDecider struct {
	dec *receipt.Decision
	err error
	obs []string
}

func (f *fakeDecider) Decide(receipt.Request) (*receipt.Decision, error) { return f.dec, f.err }
func (f *fakeDecider) Observe(_ receipt.Request, s string) error {
	f.obs = append(f.obs, s)
	return nil
}

func TestCodeBuddyHookMapping(t *testing.T) {
	in := `{"session_id":"s","cwd":"/p","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"ls"}}`
	for action, want := range map[string]string{receipt.ActionAllow: "allow", receipt.ActionDeny: "deny", receipt.ActionHold: "ask", receipt.ActionRedact: "ask"} {
		fd := &fakeDecider{dec: &receipt.Decision{Action: action, Reason: "r", Receipt: receipt.Receipt{ReceiptID: "rcp-1"}}}
		out, err := CodeBuddyHook(strings.NewReader(in), fd, "a", "block")
		if err != nil || out.HookSpecificOutput.PermissionDecision != want || !strings.Contains(out.HookSpecificOutput.PermissionDecisionReason, "rcp-1") {
			t.Fatalf("%s → %+v %v", action, out, err)
		}
	}
}

func TestCodeBuddyHookFailClosedTable(t *testing.T) {
	in := `{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{}}`
	out, _ := CodeBuddyHook(strings.NewReader(in), &fakeDecider{err: errors.New("down")}, "a", "block")
	if out.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal("block mode must deny when service is down")
	}
	out, _ = CodeBuddyHook(strings.NewReader(in), &fakeDecider{err: errors.New("down")}, "a", "audit_only")
	if out.HookSpecificOutput.PermissionDecision != "allow" {
		t.Fatal("audit_only must allow when service is down")
	}
	out, _ = CodeBuddyHook(strings.NewReader(`{bad`), &fakeDecider{}, "a", "block")
	if out.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal("malformed input must deny in block mode")
	}
	out, _ = CodeBuddyHook(strings.NewReader(in), &fakeDecider{dec: &receipt.Decision{Action: "maybe"}}, "a", "block")
	if out.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal("unknown action must deny")
	}
}

func TestCodeBuddyPostToolUseObservesAndNeverBlocks(t *testing.T) {
	fd := &fakeDecider{}
	in := `{"hook_event_name":"PostToolUse","tool_name":"WebFetch","tool_response":"` + strings.Repeat("x", 70*1024) + `"}`
	out, err := CodeBuddyHook(strings.NewReader(in), fd, "a", "block")
	if err != nil || out.HookSpecificOutput.PermissionDecision != "" || len(fd.obs) != 1 || len(fd.obs[0]) != 64*1024 {
		t.Fatalf("%+v %v %d", out, err, len(fd.obs))
	}
}
