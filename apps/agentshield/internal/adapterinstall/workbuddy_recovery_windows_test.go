package adapterinstall

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/state"
)

func crashWorkBuddyInstall(t *testing.T, o Options) {
	t.Helper()
	raw, err := json.Marshal(o)
	if err != nil {
		t.Fatal(err)
	}
	// Reuse the existing test-only child boundary; the public Prepare/Apply
	// path creates the encrypted plan, claim, audit and host file changes.
	cmd := exec.Command(os.Args[0], "-test.run=^TestAdapterCrashHelper$")
	cmd.Env = append(os.Environ(), "SIQ_TEST_ADAPTER_CRASH_OPTIONS="+string(raw), "SIQ_TEST_ADAPTER_CRASH_BOUNDARY=audited")
	err = cmd.Run()
	var exited *exec.ExitError
	if !errors.As(err, &exited) || exited.ExitCode() != 73 {
		t.Fatalf("child did not reach interrupted Apply: %v", err)
	}
}

func TestWorkBuddyRecoveryRealInterruptedApplyBindsAuthenticatedRoot(t *testing.T) {
	for _, managed := range []bool{false, true} {
		name := "legacy"
		if managed {
			name = "managed"
		}
		t.Run(name, func(t *testing.T) {
			o := workBuddyManagedOptions(t)
			if !managed {
				o.RuntimeIdentityID, o.Instance = "", nil
			}
			root := o.configRoot()
			expected := testPlan(t, o, "install")
			crashWorkBuddyInstall(t, o)
			if _, err := Prepare(o, "install"); !errors.Is(err, ErrRecoveryRequired) {
				t.Fatalf("interrupted product operation not recognized: %v", err)
			}
			// Simulate a legitimate switch to a new discovered WorkBuddy root.
			other := filepath.Join(o.Home, "other-workbuddy")
			putTestFile(t, filepath.Join(other, "settings.json"), []byte(`{"unrelated":true}`), 0600)
			t.Setenv("WORKBUDDY_CONFIG_DIR", other)
			wrong := WithWorkBuddyInstance(o, other)
			// An unauthenticated claim summary must not override the sealed plan.
			st := &state.Store{Dir: o.StateDir}
			revision, raw, err := st.LatestSeq("adapter-operations", WorkBuddy)
			if err != nil {
				t.Fatal(err)
			}
			var claim operationClaim
			if err := json.Unmarshal(raw, &claim); err != nil {
				t.Fatal(err)
			}
			claim.Record.ConfigDir, claim.Record.InstanceID = other, wrong.Instance.ID
			if _, err := st.PutVersionedCAS("adapter-operations", WorkBuddy, revision, claim); err != nil {
				t.Fatal(err)
			}
			before, err := os.ReadFile(filepath.Join(o.StateDir, "audit.jsonl"))
			if err != nil {
				t.Fatal(err)
			}
			if res, err := RecoverInstance(wrong); !errors.Is(err, ErrPlanChanged) || res != nil {
				t.Fatalf("different instance recovered old root: %v %v", res, err)
			}
			after, _ := os.ReadFile(filepath.Join(o.StateDir, "audit.jsonl"))
			if !bytes.Equal(before, after) {
				t.Fatal("rejected scope started recovery audit")
			}
			for _, change := range expected.payload.Files {
				got, err := readImage(o.Home, change.Path)
				if err != nil || !sameImage(got, change.After) {
					t.Fatal("wrong-root request changed original operation files")
				}
			}
			t.Setenv("WORKBUDDY_CONFIG_DIR", "")
			userFile := filepath.Join(root, "user-added.txt")
			putTestFile(t, userFile, []byte("preserve user file"), 0600)
			res, err := RecoverInstance(WithWorkBuddyInstance(o, root))
			if err != nil || res.Action != "rolled_back" {
				t.Fatalf("original instance recovery: %v %v", res, err)
			}
			assertBefore(t, expected)
			if raw, _ := os.ReadFile(userFile); string(raw) != "preserve user file" {
				t.Fatal("user-added file changed")
			}
			if raw, _ := os.ReadFile(filepath.Join(other, "settings.json")); string(raw) != `{"unrelated":true}` {
				t.Fatal("other instance changed")
			}
			events, err := st.TailAudit(100)
			if err != nil {
				t.Fatal(err)
			}
			started, finished := 0, 0
			for _, event := range events {
				if event.Event == "adapter_recovery_started" {
					started++
				}
				if event.Event == "adapter_recovery_rolled_back" {
					finished++
				}
			}
			if started != 1 || finished != 1 {
				t.Fatalf("recovery audit missing or duplicated: %d %d", started, finished)
			}
			if res, err = RecoverInstance(o); err != nil || res.Action != "no_recovery_needed" {
				t.Fatalf("completed recovery not idempotent: %v %v", res, err)
			}
		})
	}
}

func TestWorkBuddyRecoveryPreservesForeignConfigAfterInterruption(t *testing.T) {
	o := workBuddyManagedOptions(t)
	expected := testPlan(t, o, "install")
	crashWorkBuddyInstall(t, o)
	settings := filepath.Join(o.configRoot(), "settings.json")
	foreign := []byte(`{"user_added_after_crash":true}`)
	putTestFile(t, settings, foreign, 0600)
	res, err := RecoverInstance(o)
	if !errors.Is(err, ErrRecoveryRequired) || res == nil || res.Action != "recovery_required" {
		t.Fatalf("foreign config not reported: %v %v", res, err)
	}
	if raw, _ := os.ReadFile(settings); !bytes.Equal(raw, foreign) {
		t.Fatal("recovery overwrote user configuration")
	}
	// Explicit fixture repair restores the authenticated before-image; the
	// product never performs this repair or discards the user's new fields.
	for _, change := range expected.payload.Files {
		if change.Path == settings {
			putTestFile(t, settings, change.Before.Data, 0600)
		}
	}
	if res, err = RecoverInstance(o); err != nil || res.Action != "rolled_back" {
		t.Fatalf("recovery after explicit repair: %v %v", res, err)
	}
	assertBefore(t, expected)
}

// Separate test-only child entry because the shared crash helper installs.
func TestWorkBuddyRecoveryUninstallCrashHelper(t *testing.T) {
	raw := os.Getenv("SIQ_TEST_WB_UNINSTALL_CRASH_OPTIONS")
	if raw == "" {
		return
	}
	var o Options
	if json.Unmarshal([]byte(raw), &o) != nil {
		os.Exit(91)
	}
	transactionBoundary = func(at string) error {
		if at == "audited" {
			os.Exit(73)
		}
		return nil
	}
	p, err := Prepare(o, "uninstall")
	if err != nil {
		os.Exit(92)
	}
	_, _ = Apply(p)
	os.Exit(93)
}

func TestWorkBuddyRecoveryUninstallKeepsIdentityWithdrawn(t *testing.T) {
	o := workBuddyManagedOptions(t)
	if _, err := Apply(testPlan(t, o, "install")); err != nil {
		t.Fatal(err)
	}
	// The installer consumes only the presence of the withdrawal marker.
	// Runtime identity signature/revocation validation has separate tests.
	withdrawn := []byte(`{"revoked":true}`)
	putTestFile(t, managedRevocationPath(o), withdrawn, 0600)
	expected := testPlan(t, o, "uninstall")
	raw, err := json.Marshal(o)
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(os.Args[0], "-test.run=^TestWorkBuddyRecoveryUninstallCrashHelper$")
	cmd.Env = append(os.Environ(), "SIQ_TEST_WB_UNINSTALL_CRASH_OPTIONS="+string(raw))
	err = cmd.Run()
	var exited *exec.ExitError
	if !errors.As(err, &exited) || exited.ExitCode() != 73 {
		t.Fatalf("uninstall did not reach interruption: %v", err)
	}
	res, err := RecoverInstance(o)
	if err != nil || res.Action != "rolled_back" {
		t.Fatalf("interrupted uninstall recovery: %v %v", res, err)
	}
	assertBefore(t, expected)
	if got, err := os.ReadFile(managedRevocationPath(o)); err != nil || !bytes.Equal(got, withdrawn) {
		t.Fatal("file recovery changed identity withdrawal")
	}
}
