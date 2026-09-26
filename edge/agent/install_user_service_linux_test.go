//go:build linux

package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"testing"
	"time"
)

func privateUnitTemp(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.Chmod(dir, 0700); err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestExpiredInstallPlanPreservesIdentityAndGivesRecoveryAction(t *testing.T) {
	state, _, _ := scheduleJournalFixture(t)
	var plan map[string]any
	if json.Unmarshal(state.DiscoveryPlan, &plan) != nil {
		t.Fatal("fixture plan")
	}
	now := time.Now().UTC()
	plan["issued_at"] = now.Add(-20 * time.Minute).Format(time.RFC3339)
	plan["expires_at"] = now.Add(-10 * time.Minute).Format(time.RFC3339)
	plan["target_arch"] = runtime.GOARCH
	raw, err := json.Marshal(plan)
	if err != nil {
		t.Fatal(err)
	}
	state.DiscoveryPlan = raw
	state.DiscoveryPlanSHA256, err = compactPlanDigest(raw)
	if err != nil || state.Save() != nil {
		t.Fatal("fixture state")
	}
	path, _ := StateFilePath()
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	config := filepath.Join(t.TempDir(), "not-created")
	t.Setenv("XDG_CONFIG_HOME", config)
	if err := cmdInstallUserService(context.Background(), []string{"--start"}); err != errUserServicePlanWindow {
		t.Fatalf("wrong expiry result: %v", err)
	}
	after, _ := os.ReadFile(path)
	if string(before) != string(after) {
		t.Fatal("expired plan changed identity")
	}
	if _, err := os.Stat(config); !os.IsNotExist(err) {
		t.Fatal("expired plan wrote unit")
	}
}

func TestUserUnitExclusiveInstallation(t *testing.T) {
	dir := filepath.Join(privateUnitTemp(t), "config", "systemd", "user")
	body := []byte("synthetic unit, not executed\n")
	if writeUserUnit(dir, body) != nil || writeUserUnit(dir, body) != nil {
		t.Fatal("install/retry failed")
	}
	file := filepath.Join(dir, enterpriseUnitName)
	info, err := os.Stat(file)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatal("unsafe unit permissions")
	}
	if writeUserUnit(dir, []byte("different unit")) != errUserServiceInstall {
		t.Fatal("existing unit replaced")
	}
	actual, err := os.ReadFile(file)
	if err != nil || string(actual) != string(body) {
		t.Fatal("existing unit changed")
	}
	files, err := os.ReadDir(dir)
	if err != nil || len(files) != 1 {
		t.Fatal("temporary file not cleaned")
	}
}

func TestUserUnitRejectsUnsafeTargets(t *testing.T) {
	for _, scenario := range []string{"parent_symlink", "unit_symlink", "wide_directory", "wide_file", "hardlink"} {
		t.Run(scenario, func(t *testing.T) {
			dir := filepath.Join(privateUnitTemp(t), "units")
			if os.Mkdir(dir, 0700) != nil {
				t.Fatal("fixture")
			}
			body := []byte("fixture")
			file := filepath.Join(dir, enterpriseUnitName)
			must := func(err error) {
				t.Helper()
				if err != nil {
					t.Fatal(err)
				}
			}
			switch scenario {
			case "parent_symlink":
				link := filepath.Join(t.TempDir(), "alias")
				must(os.Symlink(dir, link))
				dir = link
			case "unit_symlink":
				other := filepath.Join(t.TempDir(), "other")
				must(os.WriteFile(other, body, 0600))
				must(os.Symlink(other, file))
			case "wide_directory":
				must(os.Chmod(dir, 0777))
			case "wide_file":
				must(os.WriteFile(file, body, 0600))
				must(os.Chmod(file, 0666))
			case "hardlink":
				must(os.WriteFile(file, body, 0600))
				must(os.Link(file, filepath.Join(dir, "alias")))
			}
			if writeUserUnit(dir, body) != errUserServiceInstall {
				t.Fatal("unsafe target accepted")
			}
		})
	}
}

func TestUserServiceActivationSequenceAndFailure(t *testing.T) {
	for failAt := -1; failAt < 3; failAt++ {
		var calls [][]string
		err := activateUserUnit(context.Background(), func(_ context.Context, args ...string) error {
			calls = append(calls, append([]string(nil), args...))
			if len(calls)-1 == failAt {
				return errors.New("synthetic manager error")
			}
			return nil
		})
		if failAt < 0 {
			want := [][]string{{"--user", "daemon-reload"}, {"--user", "enable", "--now", enterpriseUnitName}, {"--user", "is-active", "--quiet", enterpriseUnitName}}
			if err != nil || !reflect.DeepEqual(calls, want) {
				t.Fatal("unexpected activation sequence")
			}
		} else if err != errUserServiceInstall || len(calls) != failAt+1 {
			t.Fatal("activation continued after failure")
		}
	}
}

func TestUnconfirmedStateCannotInstallUserService(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "private")
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	config := filepath.Join(t.TempDir(), "config")
	t.Setenv("XDG_CONFIG_HOME", config)
	if (&State{DeviceIdentity: "fixture", Secret: "synthetic"}).Save() != nil {
		t.Fatal("fixture")
	}
	if cmdInstallUserService(context.Background(), []string{"--release", "unused", "--stage", "unused", "--start"}) != errUserServiceInstall {
		t.Fatal("unconfirmed install accepted")
	}
	if _, err := os.Stat(config); !os.IsNotExist(err) {
		t.Fatal("unconfirmed install wrote config")
	}
}

func TestPendingScheduleStopsInstallationBeforeUnitOrActivation(t *testing.T) {
	state, raw, now := scheduleJournalFixture(t)
	config := filepath.Join(t.TempDir(), "config")
	t.Setenv("XDG_CONFIG_HOME", config)
	journal, err := prepareScheduleJournal(state, raw, 0, true, now)
	if err != nil {
		t.Fatal(err)
	}
	path, _ := scheduleJournalPath()
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	// Deliberately no bundle/release: consent must reject before reading them,
	// writing service configuration, or attempting any real systemctl command.
	for _, start := range []bool{false, true} {
		args := []string{"--release", "absent-fixture-release", "--stage", "absent-fixture-stage"}
		if start {
			args = append(args, "--start")
		}
		if err := cmdInstallUserService(context.Background(), args); err != errUserServiceSchedule {
			t.Fatalf("pending confirmation not rejected first: %v", err)
		}
		if _, err := os.Stat(config); !os.IsNotExist(err) {
			t.Fatal("pending confirmation wrote service config")
		}
	}
	after, _ := os.ReadFile(path)
	if string(before) != string(after) {
		t.Fatal("installation changed recovery journal")
	}
	if err := saveScheduleConfirmation(journal, &DiscoveryScheduleState{
		Schema: "enterprise-discovery-schedule-state/v1", ScheduleID: journal.Request.ScheduleID,
		Status: "active", Revision: 1, IntentDigest: journal.Request.IntentDigest,
	}); err != nil {
		t.Fatal(err)
	}
	// The shared fixture's plan has a historical window. Recovery must not
	// bypass that window; the dedicated release tests cover valid-window bundles.
	if err := cmdInstallUserService(context.Background(), []string{"--release", "absent-fixture-release"}); err != errUserServicePlanWindow {
		t.Fatalf("recovery bypassed installation window: %v", err)
	}
}

func TestCancelledUserServiceInstallDoesNotCreateLocalState(t *testing.T) {
	root := privateUnitTemp(t)
	state := filepath.Join(root, "state")
	config := filepath.Join(root, "config")
	t.Setenv("SIQ_EDGE_STATE_DIR", state)
	t.Setenv("XDG_CONFIG_HOME", config)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if cmdInstallUserService(ctx, []string{"--start"}) != errUserServiceInstall {
		t.Fatal("cancelled install accepted")
	}
	for _, path := range []string{state, config} {
		if _, err := os.Lstat(path); !os.IsNotExist(err) {
			t.Fatal("cancelled install created local state")
		}
	}
}

func TestUserServiceActivationStopsAtCancellationBoundary(t *testing.T) {
	for cancelAt := -1; cancelAt < 3; cancelAt++ {
		ctx, cancel := context.WithCancel(context.Background())
		if cancelAt == -1 {
			cancel()
		}
		calls := 0
		err := activateUserUnit(ctx, func(context.Context, ...string) error {
			if calls == cancelAt {
				cancel()
			}
			calls++
			// A manager can finish successfully at the same time as cancellation.
			return nil
		})
		cancel()
		if err != errUserServiceInstall || calls != cancelAt+1 {
			t.Fatalf("cancelAt=%d calls=%d err=%v", cancelAt, calls, err)
		}
	}
}
