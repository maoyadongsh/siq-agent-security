//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func upgradeApplyFixture(t *testing.T) (*upgradeFixture, upgradeApplyDeps, []string) {
	t.Helper()
	f := newUpgradeFixture(t)
	review, err := inspectUpgrade(context.Background(), f.o, func() time.Time { return f.now }, f.verifier)
	if err != nil {
		t.Fatal(err)
	}
	d := upgradeApplyDeps{now: func() time.Time { return f.now }, verify: f.verifier, probe: func(context.Context, upgradeSide) error { return nil }, checkpoint: func(string) error { return nil }}
	d.manager = func(ctx context.Context, args ...string) ([]byte, error) {
		if reflect.DeepEqual(args, []string{"--user", "daemon-reload"}) {
			return nil, nil
		}
		if len(args) != 5 || args[0] != "--user" || args[1] != "show" || args[4] != enterpriseUnitName {
			t.Fatalf("unexpected service action: %q", args)
		}
		return []byte("LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\nControlPID=0\nFragmentPath=" + f.unit + "\nDropInPaths=\nNeedDaemonReload=no\n"), nil
	}
	args := []string{"--plan", f.o.plan, "--from-stage", f.o.from, "--to-stage", f.o.to, "--tenant", f.o.tenant, "--confirm-upgrade-sha256", review.Confirmation}
	return f, d, args
}
func recoverUpgradeArgs(args []string, direction string) []string {
	return []string{"--direction", direction, "--confirm-upgrade-sha256", args[len(args)-1]}
}

func TestUpgradeApplyChangesOnlyConfirmedConfiguration(t *testing.T) {
	f, d, args := upgradeApplyFixture(t)
	ledger := filepath.Join(f.root, "state", "preserved-ledger.json")
	if os.WriteFile(ledger, []byte("preserve"), 0600) != nil {
		t.Fatal("fixture")
	}
	var out bytes.Buffer
	if err := runUpgradeApply(context.Background(), args, false, &out, d); err != nil {
		t.Fatal(err)
	}
	var result upgradeCompletion
	if json.Unmarshal(out.Bytes(), &result) != nil || result.Status != "configured_not_started" || result.Direction != "target" || result.ServiceStarted || result.BusinessPermissions {
		t.Fatal("incorrect completion")
	}
	state, err := LoadState()
	if err != nil || state.Secret != f.state.Secret || state.SignerSeed != f.state.SignerSeed || state.DeviceIdentity != f.state.DeviceIdentity {
		t.Fatal("identity changed", err)
	}
	plan, _ := json.Marshal(f.next)
	expectedState, _ := upgradeStateBytes(f.state, plan)
	actual, _ := os.ReadFile(result.Journal.Intent.StatePath)
	expectedUnit, _ := upgradeUnit(f.o.to, filepath.Dir(result.Journal.Intent.StatePath))
	unit, _ := os.ReadFile(f.unit)
	if !bytes.Equal(actual, expectedState) || !bytes.Equal(unit, expectedUnit) || requireNoUpgradePending() != nil {
		t.Fatal("configuration not durable")
	}
	archived, err := readDeviceState(completionPath(&result.Journal))
	var stored upgradeCompletion
	if err != nil || json.Unmarshal(archived, &stored) != nil || !reflect.DeepEqual(stored, result) {
		t.Fatal("completion missing")
	}
	if raw, _ := os.ReadFile(ledger); string(raw) != "preserve" {
		t.Fatal("ledger changed")
	}
	if bytes.Contains(out.Bytes(), []byte(f.state.Secret)) || bytes.Contains(out.Bytes(), []byte(f.state.SignerSeed)) {
		t.Fatal("credential leaked")
	}
	if unlock, err := acquireTaskLock(); err != nil {
		t.Fatal(err)
	} else {
		unlock()
	}
	if path := os.Getenv("SIQ_UPGRADE_APPLY_WIRE_SAMPLE"); path != "" {
		if os.WriteFile(path, out.Bytes(), 0600) != nil {
			t.Fatal("sample")
		}
	}
}

func TestUpgradeApplyFaultRecoveryBothDirections(t *testing.T) {
	for _, point := range []string{"state", "unit", "reload"} {
		for _, direction := range []string{"target", "previous"} {
			t.Run(point+"-"+direction, func(t *testing.T) {
				f, d, args := upgradeApplyFixture(t)
				normal := d.checkpoint
				d.checkpoint = func(p string) error {
					if p == point {
						return errors.New("synthetic interruption")
					}
					return nil
				}
				var out bytes.Buffer
				if runUpgradeApply(context.Background(), args, false, &out, d) == nil || out.Len() != 0 || requireNoUpgradePending() == nil {
					t.Fatal("interruption not contained")
				}
				if unlock, err := acquireTaskLock(); err == nil {
					unlock()
					t.Fatal("pending allowed tasks")
				}
				d.checkpoint = normal
				if direction == "previous" {
					f.now = f.now.Add(time.Hour)
				} // Old window expired; rollback remains available.
				if err := runUpgradeApply(context.Background(), recoverUpgradeArgs(args, direction), true, &out, d); err != nil {
					t.Fatal(err)
				}
				state, err := LoadState()
				if err != nil {
					t.Fatal(err)
				}
				chosen := f.old
				if direction == "target" {
					chosen = f.next
				}
				got, _ := json.Marshal(chosen)
				digest, _ := compactPlanDigest(got)
				if state.DiscoveryPlanSHA256 != digest || requireNoUpgradePending() != nil {
					t.Fatal("wrong restored plan")
				}
			})
		}
	}
}

func TestUpgradeApplyCompletionCleanupCannotChangeDirection(t *testing.T) {
	f, d, args := upgradeApplyFixture(t)
	d.checkpoint = func(p string) error {
		if p == "archive" {
			return errors.New("crash")
		}
		return nil
	}
	if runUpgradeApply(context.Background(), args, false, &bytes.Buffer{}, d) == nil {
		t.Fatal("fault ignored")
	}
	before := upgradeTree(t, f.root)
	d.checkpoint = func(string) error { return nil }
	if runUpgradeApply(context.Background(), recoverUpgradeArgs(args, "previous"), true, &bytes.Buffer{}, d) == nil {
		t.Fatal("committed direction changed")
	}
	if !reflect.DeepEqual(before, upgradeTree(t, f.root)) {
		t.Fatal("opposite completion overwritten")
	}
	f.now = f.now.Add(time.Hour) // This is cleanup of an already committed result, not a new installation.
	if err := runUpgradeApply(context.Background(), recoverUpgradeArgs(args, "target"), true, &bytes.Buffer{}, d); err != nil {
		t.Fatal(err)
	}
}

func TestUpgradeApplyExpiredTargetAndWrongConfirmationPreservePending(t *testing.T) {
	f, d, args := upgradeApplyFixture(t)
	d.checkpoint = func(p string) error {
		if p == "state" {
			return errors.New("crash")
		}
		return nil
	}
	if runUpgradeApply(context.Background(), args, false, &bytes.Buffer{}, d) == nil {
		t.Fatal("fault")
	}
	d.checkpoint = func(string) error { return nil }
	f.now = f.now.Add(time.Hour)
	before := upgradeTree(t, f.root)
	if runUpgradeApply(context.Background(), recoverUpgradeArgs(args, "target"), true, &bytes.Buffer{}, d) == nil {
		t.Fatal("expired installation accepted")
	}
	bad := recoverUpgradeArgs(args, "previous")
	bad[3] = strings.Repeat("0", 64)
	if runUpgradeApply(context.Background(), bad, true, &bytes.Buffer{}, d) == nil {
		t.Fatal("wrong confirmation")
	}
	if !reflect.DeepEqual(before, upgradeTree(t, f.root)) {
		t.Fatal("failed recovery mutated files")
	}
	if err := runUpgradeApply(context.Background(), recoverUpgradeArgs(args, "previous"), true, &bytes.Buffer{}, d); err != nil {
		t.Fatal(err)
	}
}

func TestUpgradeApplyPreflightAndManagerFailure(t *testing.T) {
	for _, kind := range []string{"active", "probe", "signature", "reload", "cancel"} {
		t.Run(kind, func(t *testing.T) {
			f, d, args := upgradeApplyFixture(t)
			originalState, _ := os.ReadFile(filepath.Join(f.root, "state", "state.json"))
			oldUnit, _ := os.ReadFile(f.unit)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			manager := d.manager
			switch kind {
			case "active":
				d.manager = func(ctx context.Context, a ...string) ([]byte, error) {
					raw, e := manager(ctx, a...)
					return bytes.ReplaceAll(raw, []byte("ActiveState=inactive"), []byte("ActiveState=active")), e
				}
			case "probe":
				d.probe = func(context.Context, upgradeSide) error { return errUpgradeProtocol }
			case "signature":
				d.verify = realUpgradeDeps().verify
			case "cancel":
				cancel()
			case "reload":
				d.manager = func(ctx context.Context, a ...string) ([]byte, error) {
					if len(a) == 2 {
						return nil, errors.New("reload failed")
					}
					return manager(ctx, a...)
				}
			}
			var out bytes.Buffer
			if runUpgradeApply(ctx, args, false, &out, d) == nil || out.Len() != 0 {
				t.Fatal("fault accepted")
			}
			if kind == "reload" {
				if requireNoUpgradePending() == nil {
					t.Fatal("failed reload lost marker")
				}
			} else {
				state, _ := os.ReadFile(filepath.Join(f.root, "state", "state.json"))
				unit, _ := os.ReadFile(f.unit)
				if !bytes.Equal(state, originalState) || !bytes.Equal(unit, oldUnit) || requireNoUpgradePending() != nil {
					t.Fatal("preflight changed config")
				}
			}
		})
	}
}

func TestUpgradeApplyRejectsDriftDuringProbeAndAfterArchive(t *testing.T) {
	for _, where := range []string{"probe", "archive"} {
		t.Run(where, func(t *testing.T) {
			f, d, args := upgradeApplyFixture(t)
			j := prepareJournalFixture(t, f)
			bad := []byte("unauthorized third unit")
			mutate := func() {
				if os.WriteFile(f.unit, bad, 0600) != nil {
					t.Fatal("fixture")
				}
			}
			if where == "probe" {
				d.probe = func(context.Context, upgradeSide) error { mutate(); return nil }
			} else {
				d.checkpoint = func(p string) error {
					if p == "archive" {
						mutate()
					}
					return nil
				}
			}
			if runUpgradeApply(context.Background(), recoverUpgradeArgs(args, "target"), true, &bytes.Buffer{}, d) == nil {
				t.Fatal("third unit accepted")
			}
			unit, _ := os.ReadFile(f.unit)
			if !bytes.Equal(unit, bad) || requireNoUpgradePending() == nil {
				t.Fatal("third unit overwritten or marker removed")
			}
			if j.Intent.UnitPath != f.unit {
				t.Fatal("fixture")
			}
		})
	}
}

func TestUpgradeStoppedServiceExactShape(t *testing.T) {
	f, d, _ := upgradeApplyFixture(t)
	base, _ := d.manager(context.Background(), "--user", "show", "--no-pager", "unused", enterpriseUnitName)
	for _, change := range []struct{ old, next string }{
		{"LoadState=loaded", "LoadState=masked"}, {"ActiveState=inactive", "ActiveState=activating"}, {"SubState=dead", "SubState=auto-restart"}, {"MainPID=0", "MainPID=123"}, {"ControlPID=0", "ControlPID=1"}, {"DropInPaths=", "DropInPaths=/tmp/override"}, {"FragmentPath=" + f.unit, "FragmentPath=/tmp/other"}, {"NeedDaemonReload=no", "NeedDaemonReload=unknown"}, {"DropInPaths=\n", "Unknown=\n"}, {"MainPID=0\n", "MainPID=0\nMainPID=0\n"},
	} {
		t.Run(change.next, func(t *testing.T) {
			raw := bytes.ReplaceAll(base, []byte(change.old), []byte(change.next))
			run := func(context.Context, ...string) ([]byte, error) { return raw, nil }
			if requireUpgradeStopped(context.Background(), f.unit, false, run) == nil {
				t.Fatal("unsafe manager accepted")
			}
		})
	}
	reload := func(context.Context, ...string) ([]byte, error) {
		return bytes.ReplaceAll(base, []byte("NeedDaemonReload=no"), []byte("NeedDaemonReload=yes")), nil
	}
	if requireUpgradeStopped(context.Background(), f.unit, true, reload) == nil || requireUpgradeStopped(context.Background(), f.unit, false, reload) != nil {
		t.Fatal("reload distinction")
	}
}

func TestUpgradeApplyOutputFailureKeepsDurableCompletion(t *testing.T) {
	f, d, args := upgradeApplyFixture(t)
	if runUpgradeApply(context.Background(), args, false, shortUpgradeWriter{}, d) == nil {
		t.Fatal("short write accepted")
	}
	if requireNoUpgradePending() != nil {
		t.Fatal("output error rolled back completion")
	}
	archive := filepath.Join(f.root, "state", "enterprise-upgrade-completed-"+args[len(args)-1]+".json")
	if _, err := readDeviceState(archive); err != nil {
		t.Fatal("completion not recoverable from disk", err)
	}
}

func TestUpgradeProtocolPinnedProgram(t *testing.T) {
	root := privateUnitTemp(t)
	binary := filepath.Join(root, "edge-agent")
	cmd := exec.Command("go", "build", "-trimpath", "-o", binary, "./testdata/upgrade-helper")
	if raw, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("helper build %v %s", err, raw)
	}
	if os.Chmod(binary, 0500) != nil {
		t.Fatal("fixture")
	}
	raw, _ := os.ReadFile(binary)
	digest := upgradeDigest(raw)
	t.Setenv("SIQ_EDGE_STATE_DIR", "must-not-reach-child")
	if err := probeUpgradeProgram(context.Background(), binary, digest, "probe-fixture"); err != nil {
		t.Fatal(err)
	}
	if probeUpgradeProgram(context.Background(), binary, digest, "wrong-version") == nil {
		t.Fatal("wrong version accepted")
	}
	if probeUpgradeProgram(context.Background(), binary, strings.Repeat("0", 64), "probe-fixture") == nil {
		t.Fatal("wrong digest accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if probeUpgradeProgram(ctx, binary, digest, "probe-fixture") == nil {
		t.Fatal("cancel ignored")
	}
}

func TestUpgradeApplyExpiryDuringProbeDoesNotWrite(t *testing.T) {
	f, d, args := upgradeApplyFixture(t)
	prepareJournalFixture(t, f)
	beforeState, _ := os.ReadFile(filepath.Join(f.root, "state", "state.json"))
	beforeUnit, _ := os.ReadFile(f.unit)
	d.probe = func(context.Context, upgradeSide) error { f.now = f.now.Add(time.Hour); return nil }
	if runUpgradeApply(context.Background(), recoverUpgradeArgs(args, "target"), true, &bytes.Buffer{}, d) == nil {
		t.Fatal("expired during source probe")
	}
	state, _ := os.ReadFile(filepath.Join(f.root, "state", "state.json"))
	unit, _ := os.ReadFile(f.unit)
	if !bytes.Equal(state, beforeState) || !bytes.Equal(unit, beforeUnit) || requireNoUpgradePending() == nil {
		t.Fatal("expired transaction wrote configuration")
	}
}
func TestUpgradeApplyUnlinkFailureReportsNoSuccess(t *testing.T) {
	f, d, args := upgradeApplyFixture(t)
	d.checkpoint = func(p string) error {
		if p == "unlink" {
			return errors.New("directory durability unconfirmed")
		}
		return nil
	}
	var out bytes.Buffer
	if runUpgradeApply(context.Background(), args, false, &out, d) == nil || out.Len() != 0 {
		t.Fatal("false durable success")
	}
	if _, err := readDeviceState(filepath.Join(f.root, "state", "enterprise-upgrade-completed-"+args[len(args)-1]+".json")); err != nil {
		t.Fatal("archive lost", err)
	}
	if requireNoUpgradePending() != nil {
		t.Fatal("fixture is after unlink")
	}
}

func TestUpgradeApplyRecoversAfterAbruptProcessExit(t *testing.T) {
	if raw := os.Getenv("SIQ_TEST_UPGRADE_APPLY_CRASH"); raw != "" {
		var args []string
		if json.Unmarshal([]byte(raw), &args) != nil {
			os.Exit(80)
		}
		f := &upgradeFixture{o: upgradeReviewOptions{plan: args[1], from: args[3], to: args[5], tenant: args[7]}}
		config, _ := os.UserConfigDir()
		unit := filepath.Join(config, "systemd", "user", enterpriseUnitName)
		d := upgradeApplyDeps{now: time.Now, verify: f.verifier, probe: func(context.Context, upgradeSide) error { return nil },
			manager: func(_ context.Context, a ...string) ([]byte, error) {
				if len(a) == 2 && a[1] == "daemon-reload" {
					return nil, nil
				}
				return []byte("LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\nControlPID=0\nFragmentPath=" + unit + "\nDropInPaths=\nNeedDaemonReload=no\n"), nil
			}, checkpoint: func(point string) error {
				if point == "unit" {
					os.Exit(79)
				}
				return nil
			}}
		_ = runUpgradeApply(context.Background(), args, false, &bytes.Buffer{}, d)
		os.Exit(81)
	}
	f, d, args := upgradeApplyFixture(t)
	raw, _ := json.Marshal(args)
	cmd := exec.Command(os.Args[0], "-test.run=^TestUpgradeApplyRecoversAfterAbruptProcessExit$")
	cmd.Env = append(os.Environ(), "SIQ_TEST_UPGRADE_APPLY_CRASH="+string(raw))
	if err := cmd.Run(); err == nil || cmd.ProcessState.ExitCode() != 79 {
		t.Fatal("did not exit at durable unit boundary", err)
	}
	if _, err := readUpgradeJournal(context.Background(), f.verifier); err != nil {
		t.Fatal("lost recovery state", err)
	}
	if unlock, err := acquireTaskLock(); err == nil {
		unlock()
		t.Fatal("crash permitted ordinary work")
	}
	if err := runUpgradeApply(context.Background(), recoverUpgradeArgs(args, "previous"), true, &bytes.Buffer{}, d); err != nil {
		t.Fatal(err)
	}
	state, err := LoadState()
	if err != nil || state.DeviceIdentity != f.state.DeviceIdentity || state.DiscoveryPlanSHA256 != f.state.DiscoveryPlanSHA256 {
		t.Fatal("previous state not restored", err)
	}
}

func TestUpgradeProtocolRequiresExactKeys(t *testing.T) {
	raw, _ := json.Marshal(expectedUpgradeCapabilities("probe-fixture"))
	if validateUpgradeCapabilities(raw, "probe-fixture") != nil {
		t.Fatal("valid profile")
	}
	for _, bad := range [][]byte{
		bytes.ReplaceAll(raw, []byte(`"task_lock"`), []byte(`"Task_Lock"`)),
		append([]byte(`{"Task_Lock":true,`), raw[1:]...),
		append([]byte(`{"task_lock":true,`), raw[1:]...),
		bytes.ReplaceAll(raw, []byte(`"task_lock":true`), []byte(`"task_lock":null`)),
		bytes.ReplaceAll(raw, []byte(`"task_lock":true`), []byte(`"task_lock":1`)),
	} {
		if validateUpgradeCapabilities(bad, "probe-fixture") == nil {
			t.Fatal("non-contract profile accepted")
		}
	}
}
