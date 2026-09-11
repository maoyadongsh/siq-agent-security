package runtimecheck

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/intent"
)

func TestRecoveryFindsBindingPublishedBeforeJournalUpdate(t *testing.T) {
	fx := newManagerFixture(t)
	id := "rc-" + strings.Repeat("a", 32)
	now := time.Now().UTC()
	r := &run{id: id, record: record{Revision: -1, Actor: "operator", IntentID: "rci-" + strings.Repeat("a", 32), Result: Result{SchemaVersion: "local-runtime-check-result/v1", ID: id, InstanceID: testInstance, Status: "preparing", StartedAt: now.Format(time.RFC3339Nano), ExpiresAt: now.Add(Duration).Format(time.RFC3339Nano), Cleanup: "pending", Checks: map[string]bool{}, ReceiptIDs: []string{}, Limitations: limitations(), Snapshot: strings.Repeat("a", 64)}}}
	if err := fx.m.persist(&r.record); err != nil {
		t.Fatal(err)
	}
	if _, err := fx.m.prepare(r); err != nil {
		t.Fatal(err)
	}
	r.record.Result.Status = "waiting_host"
	if err := fx.m.persist(&r.record); err != nil {
		t.Fatal(err)
	}
	binding, err := fx.m.o.Intents.Bind(intent.Binding{Platform: "hermes", AgentID: agentID(id), SessionID: "native-interrupted", IntentID: r.record.IntentID})
	if err != nil {
		t.Fatal(err)
	}
	// No host is executed in this crash-window storage test. The signed journal
	// deliberately lacks the binding ID that already exists in the Intent store.
	recovered, err := New(fx.m.o)
	if err != nil {
		t.Fatal(err)
	}
	fx.m = recovered
	out, err := recovered.Get(id)
	if err != nil || out.Status != "failed" || out.Reason != "runtime_check_interrupted" || out.Cleanup != "complete" {
		t.Fatal(out, err)
	}
	if _, err := recovered.o.Intents.GetBindingRevocation(binding.BindingID); err != nil {
		t.Fatal("orphan binding not revoked", err)
	}
	if _, err := os.Stat(recovered.materials(id)); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("materials remained")
	}
	grants, err := recovered.o.Store.ListGrants()
	if err != nil || len(grants) != 1 || grants[0].Status != "revoked" {
		t.Fatal(grants, err)
	}
	if _, err := New(recovered.o); err != nil {
		t.Fatal("repeat recovery not idempotent", err)
	}
}

func TestAuditFailureNeverStartsHostOrReportsPass(t *testing.T) {
	for _, when := range []string{"before_start", "at_finish"} {
		t.Run(when, func(t *testing.T) {
			fx := newManagerFixture(t)
			fx.m.launchHost = func(_ context.Context, r *run, _ adapterinstall.RuntimeTarget, nonce string, p probes) error {
				if when == "before_start" {
					t.Error("host started despite missing audit")
					return nil
				}
				if err := fx.runProbes(r, nonce, p, true); err != nil {
					return err
				}
				audit := filepath.Join(fx.m.o.Store.Dir, "audit.jsonl")
				if err := os.Rename(audit, audit+".fixture-backup"); err != nil {
					return err
				}
				return os.Mkdir(audit, 0700)
			}
			if when == "before_start" {
				if err := os.Mkdir(filepath.Join(fx.m.o.Store.Dir, "audit.jsonl"), 0700); err != nil {
					t.Fatal(err)
				}
			}
			plan, err := fx.m.Preview(testInstance, "admin")
			if err != nil {
				t.Fatal(err)
			}
			_, err = fx.m.Start(plan.ID, plan.Digest, "admin", "operator")
			if when == "before_start" && err == nil {
				t.Fatal("start succeeded without audit")
			}
			if when == "at_finish" && err != nil {
				t.Fatal(err)
			}
			out := awaitResult(t, fx.m, plan.ID)
			if out.Status != "failed" || out.Reason != "runtime_check_audit_failed" || out.FinishedAt == nil || out.Cleanup != "complete" {
				t.Fatal(out)
			}
		})
	}
}

func TestCleanupRefusesSymlinkAndCanBeRetriedAfterRepair(t *testing.T) {
	fx := newManagerFixture(t)
	outside := t.TempDir()
	sentinel := filepath.Join(outside, "sentinel")
	if err := os.WriteFile(sentinel, []byte("preserve"), 0600); err != nil {
		t.Fatal(err)
	}
	parent := filepath.Join(fx.m.o.Store.Dir, "runtime-check-materials")
	fx.m.launchHost = func(context.Context, *run, adapterinstall.RuntimeTarget, string, probes) error {
		if err := os.Rename(parent, parent+".owned"); err != nil {
			return err
		}
		if err := os.Symlink(outside, parent); err != nil {
			return err
		}
		return errors.New("runtime_check_fixture_interruption")
	}
	plan, _ := startFixture(t, fx)
	out := awaitResult(t, fx.m, plan.ID)
	if out.Status != "failed" || out.Cleanup != "failed" {
		t.Fatal(out)
	}
	other, err := fx.m.Preview(testInstance, "admin")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := fx.m.Start(other.ID, other.Digest, "admin", "operator"); err == nil {
		t.Fatal("new check bypassed failed cleanup")
	}
	if err := os.Remove(parent); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(parent+".owned", parent); err != nil {
		t.Fatal(err)
	}
	out, err = fx.m.RetryCleanup(plan.ID)
	if err != nil || out.Cleanup != "complete" || out.Status == "passed" {
		t.Fatal(out, err)
	}
	if raw, err := os.ReadFile(sentinel); err != nil || string(raw) != "preserve" {
		t.Fatal("foreign materials changed", err)
	}
}

func TestPreviewExpiryReplacementAndCapacity(t *testing.T) {
	fx := newManagerFixture(t)
	one, err := fx.m.Preview(testInstance, "admin")
	if err != nil {
		t.Fatal(err)
	}
	two, err := fx.m.Preview(testInstance, "admin")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := fx.m.Start(one.ID, one.Digest, "admin", "operator"); err != ErrNotFound {
		t.Fatal("old preview retained", err)
	}
	old := fx.m.plans[two.ID]
	old.view.ExpiresAt = time.Now().Add(-time.Second).Format(time.RFC3339Nano)
	fx.m.plans[two.ID] = old
	if _, err := fx.m.Start(two.ID, two.Digest, "admin", "operator"); err != ErrConflict {
		t.Fatal(err)
	}
	for i := 0; i < 8; i++ {
		if _, err := fx.m.Preview(testInstance, fmt.Sprintf("admin-%d", i)); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := fx.m.Preview(testInstance, "admin-overflow"); err == nil {
		t.Fatal("preview capacity exceeded")
	}
}

func TestTamperedOrTrailingRecordCannotBeReadAsPassed(t *testing.T) {
	for _, attack := range []string{"tamper", "trailing"} {
		t.Run(attack, func(t *testing.T) {
			fx := newManagerFixture(t)
			fx.m.launchHost = func(_ context.Context, r *run, _ adapterinstall.RuntimeTarget, nonce string, p probes) error {
				return fx.runProbes(r, nonce, p, true)
			}
			plan, _ := startFixture(t, fx)
			_ = awaitResult(t, fx.m, plan.ID)
			all, err := fx.m.records()
			if err != nil {
				t.Fatal(err)
			}
			r := all[plan.ID]
			file := filepath.Join(fx.m.dir(), fmt.Sprintf("%s.%06d.json", plan.ID, r.Revision))
			raw, err := os.ReadFile(file)
			if err != nil {
				t.Fatal(err)
			}
			if attack == "trailing" {
				raw = append(raw, []byte("{}")...)
			} else {
				raw = []byte(strings.Replace(string(raw), "runtime_check_passed", "runtime_check_forged", 1))
			}
			if err := os.WriteFile(file, raw, 0600); err != nil {
				t.Fatal(err)
			}
			if _, err := fx.m.Get(plan.ID); err == nil {
				t.Fatal("corrupt evidence accepted")
			}
		})
	}
}
