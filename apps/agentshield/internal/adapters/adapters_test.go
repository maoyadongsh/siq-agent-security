package adapters

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
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
		in := `{"protocolVersion":1,"targetType":"skill","targetName":"x","source":{"kind":"clawhub","locator":"clawhub:x"},"sourcePathKind":"directory","sourcePath":"` + fixture(rel) + `"}`
		out := PolicyExec(strings.NewReader(in), deps(t))
		if out.ProtocolVersion != 1 || out.Decision != want {
			t.Fatalf("%s: got %s (%s)", rel, out.Decision, out.Reason)
		}
		if out.AdmissionID == "" || out.Verdict == "" {
			t.Fatalf("%s: response must carry admission id and verdict", rel)
		}
	}
}

func TestPolicyExecFailsClosed(t *testing.T) {
	for name, in := range map[string]string{
		"malformed":       `{not json`,
		"no path":         `{"protocolVersion":1,"targetType":"skill","targetName":"x","sourcePathKind":"directory"}`,
		"old protocol":    `{"targetType":"skill","stagedPath":"` + fixture("benign/pure-doc") + `"}`,
		"future protocol": `{"protocolVersion":2,"targetType":"skill","targetName":"x","sourcePathKind":"directory","sourcePath":"` + fixture("benign/pure-doc") + `"}`,
		"missing dir":     `{"protocolVersion":1,"targetType":"skill","targetName":"x","sourcePathKind":"directory","sourcePath":"/nonexistent/skill"}`,
		"file not dir":    `{"protocolVersion":1,"targetType":"skill","targetName":"x","sourcePathKind":"directory","sourcePath":"` + fixture("benign/pure-doc/SKILL.md") + `"}`,
		"wrong kind":      `{"protocolVersion":1,"targetType":"skill","targetName":"x","sourcePathKind":"file","sourcePath":"` + fixture("benign/pure-doc") + `"}`,
		"trailing object": `{"protocolVersion":1,"targetType":"skill","targetName":"x","sourcePathKind":"directory","sourcePath":"` + fixture("benign/pure-doc") + `"}{}`,
	} {
		if out := PolicyExec(strings.NewReader(in), deps(t)); out.Decision != "block" {
			t.Fatalf("%s: must block, got %s", name, out.Decision)
		}
	}
	if out := PolicyExec(strings.NewReader(`{"protocolVersion":1,"targetType":"plugin","targetName":"x","sourcePathKind":"directory","sourcePath":"/x"}`), deps(t)); out.Decision != "block" {
		t.Fatalf("plugin targets are out of scope and must block, got %s", out.Decision)
	}
	deps := deps(t)
	deps.Persist = func(*admission.Result) error { return errors.New("disk unavailable") }
	good := `{"protocolVersion":1,"targetType":"skill","targetName":"x","sourcePathKind":"directory","sourcePath":"` + fixture("benign/pure-doc") + `"}`
	if out := PolicyExec(strings.NewReader(good), deps); out.Decision != "block" {
		t.Fatalf("persistence failure must block, got %s", out.Decision)
	}
}

func TestPolicyExecRejectsSymlinkedStagedRoot(t *testing.T) {
	link := filepath.Join(t.TempDir(), "staged")
	if err := os.Symlink(fixture("benign/pure-doc"), link); err != nil {
		t.Fatal(err)
	}
	in, err := json.Marshal(map[string]any{
		"protocolVersion": 1, "targetType": "skill", "targetName": "x",
		"sourcePathKind": "directory", "sourcePath": link,
	})
	if err != nil {
		t.Fatal(err)
	}
	if got := PolicyExec(bytes.NewReader(in), deps(t)); got.Decision != "block" {
		t.Fatalf("symlink root must block, got %s", got.Decision)
	}
}

type fakeDecider struct {
	dec  *receipt.Decision
	err  error
	obs  []string
	last receipt.Request
}

func (f *fakeDecider) Decide(r receipt.Request) (*receipt.Decision, error) {
	f.last = r
	return f.dec, f.err
}
func (f *fakeDecider) Observe(_ receipt.Request, s string) error {
	f.obs = append(f.obs, s)
	return nil
}

func TestCodeBuddyHookMapping(t *testing.T) {
	in := `{"session_id":"s","cwd":"/p","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"ls"}}`
	for action, want := range map[string]string{receipt.ActionAllow: "allow", receipt.ActionDeny: "deny", receipt.ActionHold: "ask", receipt.ActionRedact: "ask"} {
		fd := &fakeDecider{dec: &receipt.Decision{Action: action, Reason: "r", Receipt: receipt.Receipt{ReceiptID: "rcp-1"}}}
		out, err := CodeBuddyHook(strings.NewReader(in), fd, "a", "block", t.TempDir())
		if err != nil || out.HookSpecificOutput.PermissionDecision != want || !strings.Contains(out.HookSpecificOutput.PermissionDecisionReason, "rcp-1") {
			t.Fatalf("%s → %+v %v", action, out, err)
		}
	}
}

func TestCodeBuddyHookFailClosedTable(t *testing.T) {
	in := `{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{}}`
	state := t.TempDir()
	out, _ := CodeBuddyHook(strings.NewReader(in), &fakeDecider{err: errors.New("down")}, "a", "block", state)
	if out.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal("block mode must deny when service is down")
	}
	pendingPath := filepath.Join(state, "pending", "decisions.jsonl")
	raw, err := os.ReadFile(pendingPath)
	if err != nil || !strings.Contains(string(raw), `"signed":false`) || !strings.Contains(string(raw), "decision service unavailable") {
		t.Fatalf("fail-closed must append unsigned pending record: %v %s", err, raw)
	}
	out, _ = CodeBuddyHook(strings.NewReader(in), &fakeDecider{err: errors.New("down")}, "a", "audit_only", state)
	if out.HookSpecificOutput.PermissionDecision != "allow" {
		t.Fatal("audit_only must allow when service is down")
	}
	out, _ = CodeBuddyHook(strings.NewReader(`{bad`), &fakeDecider{}, "a", "block", state)
	if out.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal("malformed input must deny in block mode")
	}
	out, _ = CodeBuddyHook(strings.NewReader(in), &fakeDecider{dec: &receipt.Decision{Action: "maybe"}}, "a", "block", state)
	if out.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal("unknown action must deny")
	}
}

func TestHostToolHookRecordsWorkBuddyPlatform(t *testing.T) {
	in := `{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{}}`
	state := t.TempDir()
	out, err := HostToolHook(strings.NewReader(in), &fakeDecider{err: errors.New("down")}, "a", "block", state, "workbuddy")
	if err != nil || out.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatalf("%+v %v", out, err)
	}
	raw, err := os.ReadFile(filepath.Join(state, "pending", "decisions.jsonl"))
	if err != nil || !strings.Contains(string(raw), `"platform":"workbuddy"`) || strings.Contains(string(raw), `"platform":"codebuddy"`) {
		t.Fatalf("workbuddy pending must not reuse codebuddy: %v %s", err, raw)
	}
}

func TestCodeBuddyPostToolUseObservesAndNeverBlocks(t *testing.T) {
	fd := &fakeDecider{}
	in := `{"hook_event_name":"PostToolUse","tool_name":"WebFetch","tool_response":"` + strings.Repeat("x", 70*1024) + `"}`
	out, err := CodeBuddyHook(strings.NewReader(in), fd, "a", "block", t.TempDir())
	if err != nil || out.HookSpecificOutput.PermissionDecision != "" || len(fd.obs) != 1 || len(fd.obs[0]) != 64*1024 {
		t.Fatalf("%+v %v %d", out, err, len(fd.obs))
	}
}

func TestWorkBuddyHookStampsPlatformAndFailClosedDeny(t *testing.T) {
	in := `{"session_id":"wb","cwd":"/p","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"ls"}}`
	fd := &fakeDecider{dec: &receipt.Decision{Action: receipt.ActionAllow, Reason: "r", Receipt: receipt.Receipt{ReceiptID: "rcp-wb"}}}
	out, err := HostToolHook(strings.NewReader(in), fd, "a", "block", t.TempDir(), "workbuddy")
	if err != nil || out.HookSpecificOutput.PermissionDecision != "allow" || fd.last.Platform != "workbuddy" {
		t.Fatalf("platform stamp lost: %+v %+v %v", out, fd.last, err)
	}
	denied, _ := HostToolHook(strings.NewReader(in), &fakeDecider{err: errors.New("down")}, "a", "block", t.TempDir(), "workbuddy")
	if denied.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal("workbuddy block mode must deny when service is down")
	}
}
