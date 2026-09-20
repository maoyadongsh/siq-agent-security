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
		in, err := json.Marshal(map[string]any{
			"protocolVersion": 1, "targetType": "skill", "targetName": "x",
			"source":         map[string]string{"kind": "clawhub", "locator": "clawhub:x"},
			"sourcePathKind": "directory", "sourcePath": fixture(rel),
		})
		if err != nil {
			t.Fatal(err)
		}
		out := PolicyExec(bytes.NewReader(in), deps(t))
		if out.ProtocolVersion != 1 || out.Decision != want {
			t.Fatalf("%s: got %s (%s)", rel, out.Decision, out.Reason)
		}
		if out.AdmissionID == "" || out.Verdict == "" {
			t.Fatalf("%s: response must carry admission id and verdict", rel)
		}
	}
}

func TestPolicyExecFailsClosed(t *testing.T) {
	request := func(version int, kind, path string) string {
		t.Helper()
		raw, err := json.Marshal(PolicyExecRequest{
			ProtocolVersion: version, TargetType: "skill", TargetName: "x",
			SourcePathKind: kind, SourcePath: path,
		})
		if err != nil {
			t.Fatal(err)
		}
		return string(raw)
	}
	filePath := fixture("benign/pure-doc/SKILL.md")
	if info, err := os.Stat(filePath); err != nil || !info.Mode().IsRegular() {
		t.Fatalf("file-not-directory fixture must be an existing regular file: %v", err)
	}
	good := request(1, "directory", fixture("benign/pure-doc"))
	legacy, err := json.Marshal(map[string]string{"targetType": "skill", "stagedPath": fixture("benign/pure-doc")})
	if err != nil {
		t.Fatal(err)
	}
	for name, test := range map[string]struct{ input, reason string }{
		"malformed":       {`{not json`, "malformed install policy request"},
		"no path":         {request(1, "directory", ""), "unsupported install policy request"},
		"old protocol":    {string(legacy), "unsupported install policy request"},
		"future protocol": {request(2, "directory", fixture("benign/pure-doc")), "unsupported install policy request"},
		"missing dir":     {request(1, "directory", filepath.Join(t.TempDir(), "missing")), "staged path is not a readable directory"},
		"file not dir":    {request(1, "directory", filePath), "staged path is not a readable directory"},
		"wrong kind":      {request(1, "file", fixture("benign/pure-doc")), "unsupported install policy request"},
		"trailing object": {good + `{}`, "malformed install policy request"},
	} {
		t.Run(name, func(t *testing.T) {
			out := PolicyExec(strings.NewReader(test.input), deps(t))
			if out.ProtocolVersion != 1 || out.Decision != "block" || !strings.HasSuffix(out.Reason, ": "+test.reason) {
				t.Fatalf("must block at expected validation layer %q, got %+v", test.reason, out)
			}
		})
	}
	if out := PolicyExec(strings.NewReader(`{"protocolVersion":1,"targetType":"plugin","targetName":"x","sourcePathKind":"directory","sourcePath":"/x"}`), deps(t)); out.Decision != "block" {
		t.Fatalf("plugin targets are out of scope and must block, got %s", out.Decision)
	}
	deps := deps(t)
	persistCalled := false
	deps.Persist = func(*admission.Result) error {
		persistCalled = true
		return errors.New("disk unavailable")
	}
	out := PolicyExec(strings.NewReader(good), deps)
	if out.Decision != "block" || !persistCalled || !strings.HasSuffix(out.Reason, ": admission persistence failed (fail-closed)") {
		t.Fatalf("persistence failure must block after the persistence callback, got %+v (called=%v)", out, persistCalled)
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

func TestWorkBuddyHookMapping(t *testing.T) {
	in := `{"session_id":"s","cwd":"/p","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"ls"}}`
	for action, want := range map[string]string{receipt.ActionAllow: "allow", receipt.ActionDeny: "deny", receipt.ActionHold: "ask", receipt.ActionRedact: "ask"} {
		fd := &fakeDecider{dec: &receipt.Decision{Action: action, Reason: "r", Receipt: receipt.Receipt{ReceiptID: "rcp-1"}}}
		out, err := WorkBuddyHook(strings.NewReader(in), fd, "a", "block", t.TempDir())
		if err != nil || out.HookSpecificOutput.PermissionDecision != want || !strings.Contains(out.HookSpecificOutput.PermissionDecisionReason, "rcp-1") {
			t.Fatalf("%s → %+v %v", action, out, err)
		}
	}
}

func TestWorkBuddyHookFailClosedTable(t *testing.T) {
	in := `{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{}}`
	state := t.TempDir()
	out, _ := WorkBuddyHook(strings.NewReader(in), &fakeDecider{err: errors.New("down")}, "a", "block", state)
	if out.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal("block mode must deny when service is down")
	}
	pendingPath := filepath.Join(state, "pending", "decisions.jsonl")
	raw, err := os.ReadFile(pendingPath)
	if err != nil || !strings.Contains(string(raw), `"signed":false`) || !strings.Contains(string(raw), "decision service unavailable") {
		t.Fatalf("fail-closed must append unsigned pending record: %v %s", err, raw)
	}
	out, _ = WorkBuddyHook(strings.NewReader(in), &fakeDecider{err: errors.New("down")}, "a", "audit_only", state)
	if out.HookSpecificOutput.PermissionDecision != "allow" {
		t.Fatal("audit_only must allow when service is down")
	}
	out, _ = WorkBuddyHook(strings.NewReader(`{bad`), &fakeDecider{}, "a", "block", state)
	if out.HookSpecificOutput.PermissionDecision != "deny" {
		t.Fatal("malformed input must deny in block mode")
	}
	out, _ = WorkBuddyHook(strings.NewReader(in), &fakeDecider{dec: &receipt.Decision{Action: "maybe"}}, "a", "block", state)
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
	if err != nil || !strings.Contains(string(raw), `"platform":"workbuddy"`) {
		t.Fatalf("pending must record the native platform: %v %s", err, raw)
	}
}

func TestWorkBuddyPostToolUseObservesAndNeverBlocks(t *testing.T) {
	fd := &fakeDecider{}
	in := `{"hook_event_name":"PostToolUse","tool_name":"WebFetch","tool_response":"` + strings.Repeat("x", 70*1024) + `"}`
	out, err := WorkBuddyHook(strings.NewReader(in), fd, "a", "block", t.TempDir())
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

func TestUnsupportedHostHooksAlwaysDenyWithoutCallingService(t *testing.T) {
	for _, platform := range []string{"codebuddy", "unknown"} {
		for _, mode := range []string{"block", "warn", "audit_only"} {
			out, err := HostToolHook(strings.NewReader(`{}`), nil, "a", mode, "", platform)
			if err != nil || out.HookSpecificOutput.PermissionDecision != "deny" {
				t.Fatalf("unsupported %s/%s: %+v %v", platform, mode, out, err)
			}
		}
	}
}
