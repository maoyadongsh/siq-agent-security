package adapters

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/pending"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

func TestWorkBuddyLocalFailurePreservesOnlyVerifiedCallEvidence(t *testing.T) {
	for _, stage := range []string{"bootstrap", "enrollment", "observation", "parse"} {
		t.Run(stage, func(t *testing.T) {
			dir := t.TempDir()
			input := workBuddyInput
			var d WorkBuddyManagedDecider
			if stage == "enrollment" {
				d = &workBuddyDecider{enrollErr: true}
			}
			if stage == "observation" {
				input = strings.Replace(input, "PreToolUse", "PostToolUse", 1)
				input = strings.TrimSuffix(input, "}") + `,"tool_response":"SECRET-RESULT"}`
			}
			if stage == "parse" {
				input = `{"session_id":"UNVALIDATED-ID","tool_input":{"secret":"SECRET-PARAM"}}`
			}
			out := WorkBuddyManagedHook(strings.NewReader(input), d, "hri-fixture", "block", dir)
			raw, err := os.ReadFile(filepath.Join(dir, "pending", "decisions.jsonl"))
			if err != nil {
				t.Fatal(err)
			}
			var rec pending.Record
			if err := json.Unmarshal(raw, &rec); err != nil {
				t.Fatal(err)
			}
			if rec.Schema != pending.LocalSchemaID || rec.Stage != stage || rec.Origin != "local_hook" || rec.ReasonCode == "" || rec.Signed {
				t.Fatalf("incomplete event: %+v", rec)
			}
			if err := pending.ValidateLocalRecord(rec); err != nil {
				t.Fatal(err)
			}
			for _, secret := range []string{"SECRET-RESULT", "SECRET-PARAM", "UNVALIDATED-ID", "tool_input", "file_path"} {
				if strings.Contains(string(raw), secret) {
					t.Fatalf("unsafe field persisted: %s", secret)
				}
			}
			if stage == "parse" {
				if rec.ToolCallID != "" || rec.NativeCallID != "" || rec.SessionID != "" || rec.ActionDigest != "" {
					t.Fatal("fabricated correlation")
				}
			} else {
				ev, _ := ParseWorkBuddyManagedInput(strings.NewReader(input))
				session, _ := runtimeidentity.WorkBuddySessionID(ev.SessionID)
				call, _ := runtimeidentity.WorkBuddyCallID(ev.SessionID, ev.CallID)
				if rec.SessionID != session || rec.ToolCallID != call || rec.NativeSessionID != ev.SessionID || rec.NativeCallID != ev.CallID || len(rec.ActionDigest) != 64 {
					t.Fatal("parsed correlation lost")
				}
			}
			if stage == "observation" {
				if rec.Outcome != "unconfirmed" || out.HookSpecificOutput.PermissionDecision != "" {
					t.Fatal("observation failure fabricated a deny")
				}
			} else if rec.Outcome != "deny" || out.HookSpecificOutput.PermissionDecision != "deny" {
				t.Fatal("failure did not close")
			}
		})
	}
}
