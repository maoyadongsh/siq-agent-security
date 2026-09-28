package adapters

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/pending"
	"siq-agent-security/apps/agentshield/internal/privatefs"
)

type codedEnrollmentFailure struct {
	workBuddyDecider
	code string
}

func (d *codedEnrollmentFailure) Enroll(string) error { return &WorkBuddyServiceFailure{Code: d.code} }

func TestWorkBuddyEnrollmentFailureCodesDoNotFabricatePolicyOrLeakErrors(t *testing.T) {
	for _, code := range []string{"workbuddy_service_unavailable", "workbuddy_identity_rejected", "workbuddy_enrollment_rejected", "workbuddy_session_expired", "https://SECRET-TRANSPORT/token"} {
		t.Run(strings.ReplaceAll(code, "/", "_"), func(t *testing.T) {
			dir := t.TempDir()
			out := WorkBuddyManagedHook(strings.NewReader(workBuddyInput), &codedEnrollmentFailure{code: code}, "hri-fixture", "block", dir)
			if out.HookSpecificOutput.PermissionDecision != "deny" {
				t.Fatal("enrollment failure allowed")
			}
			raw, err := os.ReadFile(filepath.Join(dir, "pending", "decisions.jsonl"))
			if err != nil {
				t.Fatal(err)
			}
			var rec pending.Record
			if json.Unmarshal(raw, &rec) != nil || pending.ValidateLocalRecord(rec) != nil || rec.Stage != "enrollment" {
				t.Fatal("invalid local evidence")
			}
			want := code
			if strings.Contains(code, "SECRET") {
				want = "workbuddy_enrollment_unavailable"
			}
			if rec.ReasonCode != want || strings.Contains(string(raw), "SECRET") || strings.Contains(out.HookSpecificOutput.PermissionDecisionReason, code) {
				t.Fatal("unsafe or incorrect diagnosis")
			}
		})
	}
}

func TestWorkBuddyPreflightObjectCodes(t *testing.T) {
	for _, item := range []struct {
		err  error
		want string
	}{
		{privatefs.ErrMultipleLinks, "multiple_links"}, {privatefs.ErrReparse, "reparse"},
		{privatefs.ErrOwnerMismatch, "owner_mismatch"}, {privatefs.ErrObjectChanged, "object_changed"},
		{os.ErrNotExist, "missing"}, {privatefs.ErrPrivate, "private_check_failed"},
	} {
		failure := workBuddyObjectFailure("workbuddy_config_file_unavailable", item.err).(*WorkBuddyPreflightError)
		if failure.ObjectCode != item.want || failure.ReasonCode() != failure.Code+"_"+item.want {
			t.Fatal("wrong safe object category")
		}
	}
}
