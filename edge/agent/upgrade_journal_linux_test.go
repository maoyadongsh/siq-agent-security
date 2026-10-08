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
	"syscall"
	"testing"
	"time"

	"siq-agent-security/edge/agent/installplan"
)

func prepareJournalFixture(t *testing.T, f *upgradeFixture) *upgradeJournal {
	t.Helper()
	unlock, err := acquireRawTaskLock()
	if err != nil {
		t.Fatal(err)
	}
	defer unlock()
	review, err := inspectUpgrade(context.Background(), f.o, func() time.Time { return f.now }, f.verifier)
	if err != nil {
		t.Fatal(err)
	}
	j, err := prepareUpgradeJournal(context.Background(), f.o, review.Confirmation, func() time.Time { return f.now }, f.verifier)
	if err != nil {
		t.Fatal(err)
	}
	return j
}

func journalFixturePath(f *upgradeFixture) string {
	return filepath.Join(f.root, "state", upgradePendingName)
}

func TestUpgradeJournalDurableBindingAndNoConfigurationChanges(t *testing.T) {
	f := newUpgradeFixture(t)
	statePath, _ := StateFilePath()
	stateBefore, _ := os.ReadFile(statePath)
	unitBefore, _ := os.ReadFile(f.unit)
	j := prepareJournalFixture(t, f)
	raw, err := readDeviceState(journalFixturePath(f))
	if err != nil || bytes.Contains(raw, []byte(f.state.Secret)) || bytes.Contains(raw, []byte(f.state.SignerSeed)) {
		t.Fatal("journal contains a credential or is unsafe", err)
	}
	info, _ := os.Stat(journalFixturePath(f))
	if info.Mode().Perm() != 0600 || info.Sys().(*syscall.Stat_t).Nlink != 1 {
		t.Fatal("journal privacy")
	}
	stateAfter, _ := os.ReadFile(statePath)
	unitAfter, _ := os.ReadFile(f.unit)
	if !bytes.Equal(stateBefore, stateAfter) || !bytes.Equal(unitBefore, unitAfter) {
		t.Fatal("preparation changed installed configuration")
	}
	read, err := readUpgradeJournal(context.Background(), f.verifier)
	if err != nil || !reflect.DeepEqual(read, j) || requireNoUpgradePending() == nil {
		t.Fatal("durable readback or pending marker", err)
	}
	if path := os.Getenv("SIQ_UPGRADE_JOURNAL_WIRE_SAMPLE"); path != "" {
		if os.WriteFile(path, append(raw, '\n'), 0600) != nil {
			t.Fatal("wire sample write")
		}
	}
}

func TestUpgradeJournalKnownInterruptedStates(t *testing.T) {
	for _, version := range []string{"original", "target", "restored"} {
		for _, unitVersion := range []string{"old", "new"} {
			t.Run(version+"-"+unitVersion, func(t *testing.T) {
				f := newUpgradeFixture(t)
				j := prepareJournalFixture(t, f)
				if version != "original" {
					plan := j.OriginalPlan
					if version == "target" {
						plan, _ = json.Marshal(j.Intent.To.Plan)
					}
					raw, _ := upgradeStateBytes(f.state, plan)
					if os.WriteFile(j.Intent.StatePath, raw, 0600) != nil {
						t.Fatal("state transition fixture")
					}
				}
				if unitVersion == "new" {
					unit, _ := upgradeUnit(f.o.to, filepath.Dir(j.Intent.StatePath))
					if os.WriteFile(f.unit, unit, 0600) != nil {
						t.Fatal("unit transition fixture")
					}
				}
				before := upgradeTree(t, f.root)
				if _, err := readUpgradeJournal(context.Background(), f.verifier); err != nil {
					t.Fatal("known state not inspectable", err)
				}
				if !reflect.DeepEqual(before, upgradeTree(t, f.root)) {
					t.Fatal("recovery inspection wrote files")
				}
				if unlock, err := acquireTaskLock(); err == nil {
					unlock()
					t.Fatal("ordinary execution accepted pending state")
				}
			})
		}
	}
}

func TestUpgradeJournalRefusesCompetingConsentAndCredentialWork(t *testing.T) {
	for _, name := range []string{"credential-rotation-pending.json", scheduleJournalName, "discovery-schedule-confirmed.json", scheduleRetirementPendingName, upgradePendingName} {
		t.Run(name, func(t *testing.T) {
			f := newUpgradeFixture(t)
			review, _ := inspectUpgrade(context.Background(), f.o, func() time.Time { return f.now }, f.verifier)
			path := filepath.Join(f.root, "state", name)
			if os.WriteFile(path, []byte("preserve-existing-transaction"), 0600) != nil {
				t.Fatal("fixture")
			}
			before := upgradeTree(t, f.root)
			if _, err := prepareUpgradeJournal(context.Background(), f.o, review.Confirmation, func() time.Time { return f.now }, f.verifier); err == nil {
				t.Fatal("competing transaction accepted")
			}
			if !reflect.DeepEqual(before, upgradeTree(t, f.root)) {
				t.Fatal("existing transaction changed")
			}
		})
	}
}

func TestUpgradeJournalPreparationRejectsStaleConfirmationAndSources(t *testing.T) {
	for _, mode := range []string{"confirmation", "expired", "signature", "cancel", "state-drift", "unit-drift"} {
		t.Run(mode, func(t *testing.T) {
			f := newUpgradeFixture(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			review, _ := inspectUpgrade(ctx, f.o, func() time.Time { return f.now }, f.verifier)
			verify := upgradeStageVerifier(f.verifier)
			switch mode {
			case "confirmation":
				review.Confirmation = strings.Repeat("0", 64)
			case "expired":
				f.now = f.now.Add(time.Hour)
			case "signature":
				verify = installplan.VerifyStagedBundle
			case "cancel":
				cancel()
			case "state-drift":
				f.state.Secret = "changed-synthetic-token"
				if f.state.Save() != nil {
					t.Fatal("fixture")
				}
			case "unit-drift":
				if os.WriteFile(f.unit, []byte("custom unit"), 0600) != nil {
					t.Fatal("fixture")
				}
			}
			before := upgradeTree(t, f.root)
			if _, err := prepareUpgradeJournal(ctx, f.o, review.Confirmation, func() time.Time { return f.now }, verify); err == nil {
				t.Fatal("invalid preparation accepted")
			}
			if !reflect.DeepEqual(before, upgradeTree(t, f.root)) {
				t.Fatal("failed preparation changed files")
			}
		})
	}
}

func TestUpgradeJournalIdentityAndThirdBytesRejected(t *testing.T) {
	mutations := map[string]func(*State){
		"identity":    func(s *State) { s.DeviceIdentity += "-other" },
		"secret":      func(s *State) { s.Secret += "-other" },
		"signer":      func(s *State) { s.SignerSeed += "-other" },
		"public-key":  func(s *State) { s.PublicKeyPEM = "other" },
		"control-key": func(s *State) { s.ControlPlanePublicKey = "other" },
		"environment": func(s *State) { s.EnvironmentID += "-other" },
		"origin":      func(s *State) { s.ControlPlaneURL += "/other" },
		"plan-digest": func(s *State) { s.DiscoveryPlanSHA256 = strings.Repeat("0", 64) },
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			f := newUpgradeFixture(t)
			prepareJournalFixture(t, f)
			mutate(f.state)
			if f.state.Save() != nil {
				t.Fatal("fixture")
			}
			if _, err := readUpgradeJournal(context.Background(), f.verifier); err == nil {
				t.Fatal("identity drift accepted")
			}
		})
	}
	for _, kind := range []string{"state-whitespace", "state-unknown-field", "unit", "release"} {
		t.Run(kind, func(t *testing.T) {
			f := newUpgradeFixture(t)
			j := prepareJournalFixture(t, f)
			path := j.Intent.StatePath
			raw, _ := os.ReadFile(path)
			switch kind {
			case "state-whitespace":
				raw = append(raw, '\n')
			case "state-unknown-field":
				raw = append([]byte(`{"unknown":true,`), raw[1:]...)
			case "unit":
				path, raw = f.unit, []byte("third unit")
			case "release":
				path, raw = filepath.Join(f.o.to, "release.json"), []byte("wrong release")
				if os.Chmod(path, 0600) != nil {
					t.Fatal("fixture")
				}
			}
			if os.WriteFile(path, raw, 0600) != nil {
				t.Fatal("fixture")
			}
			before := upgradeTree(t, f.root)
			if _, err := readUpgradeJournal(context.Background(), f.verifier); err == nil {
				t.Fatal("third bytes accepted")
			}
			if !reflect.DeepEqual(before, upgradeTree(t, f.root)) {
				t.Fatal("inspection repaired files")
			}
		})
	}
}

func TestUpgradeJournalDamagedRecordsBlockNormalEntrypoints(t *testing.T) {
	for _, kind := range []string{"partial", "unknown-field", "duplicate", "oversize", "link", "hardlink", "directory", "mode", "fifo"} {
		t.Run(kind, func(t *testing.T) {
			f := newUpgradeFixture(t)
			prepareJournalFixture(t, f)
			path := journalFixturePath(f)
			raw, _ := os.ReadFile(path)
			switch kind {
			case "partial":
				raw = []byte(`{"schema_version":`)
			case "unknown-field":
				raw = append([]byte(`{"other":null,`), raw[1:]...)
			case "duplicate":
				raw = append([]byte(`{"schema_version":"enterprise-upgrade-pending/v1",`), raw[1:]...)
			case "oversize":
				raw = bytes.Repeat([]byte(" "), upgradeJournalLimit+1)
			case "mode":
				if os.Chmod(path, 0644) != nil {
					t.Fatal("fixture")
				}
			case "hardlink":
				if os.Link(path, path+".copy") != nil {
					t.Fatal("fixture")
				}
			case "link", "directory", "fifo":
				if os.Rename(path, path+".saved") != nil {
					t.Fatal("fixture")
				}
				var err error
				if kind == "link" {
					err = os.Symlink(path+".saved", path)
				}
				if kind == "directory" {
					err = os.Mkdir(path, 0700)
				}
				if kind == "fifo" {
					err = syscall.Mkfifo(path, 0600)
				}
				if err != nil {
					t.Fatal(err)
				}
			}
			if kind == "partial" || kind == "unknown-field" || kind == "duplicate" || kind == "oversize" {
				if os.WriteFile(path, raw, 0600) != nil {
					t.Fatal("fixture")
				}
			}
			if _, err := readUpgradeJournal(context.Background(), f.verifier); err == nil {
				t.Fatal("damaged journal accepted")
			}
			for name, run := range map[string]func(context.Context, []string) error{"tasks": cmdTasks, "serve": cmdServe} {
				if err := run(context.Background(), nil); !errors.Is(err, errUpgradePending) {
					t.Fatalf("%s did not stop at pending boundary: %v", name, err)
				}
			}
			if unlock, err := acquireRawTaskLock(); err != nil {
				t.Fatal("recovery lock leaked", err)
			} else {
				unlock()
			}
		})
	}
}

func TestUpgradeJournalRechecksInputsAfterVerification(t *testing.T) {
	for _, kind := range []string{"journal", "state", "unit", "conflict", "cancel"} {
		t.Run(kind, func(t *testing.T) {
			f := newUpgradeFixture(t)
			j := prepareJournalFixture(t, f)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			mutated := false
			verify := func(p installplan.Plan, raw []byte, stage string) error {
				if !mutated {
					mutated = true
					switch kind {
					case "journal":
						if os.WriteFile(journalFixturePath(f), []byte("{}"), 0600) != nil {
							t.Fatal("fixture")
						}
					case "state":
						if os.WriteFile(j.Intent.StatePath, []byte("{}"), 0600) != nil {
							t.Fatal("fixture")
						}
					case "unit":
						if os.WriteFile(f.unit, []byte("changed"), 0600) != nil {
							t.Fatal("fixture")
						}
					case "conflict":
						if os.WriteFile(filepath.Join(f.root, "state", scheduleJournalName), []byte("{}"), 0600) != nil {
							t.Fatal("fixture")
						}
					case "cancel":
						cancel()
					}
				}
				return f.verifier(p, raw, stage)
			}
			if _, err := readUpgradeJournal(ctx, verify); err == nil {
				t.Fatal("in-flight mutation accepted")
			}
		})
	}
}

func TestUpgradeJournalFieldsBoundAndPublisherRechecked(t *testing.T) {
	f := newUpgradeFixture(t)
	j := prepareJournalFixture(t, f)
	if _, err := readUpgradeJournal(context.Background(), installplan.VerifyStagedBundle); err == nil {
		t.Fatal("journal bypassed fixed publisher verification")
	}
	mutations := map[string]func(*upgradeJournal){
		"schema":       func(j *upgradeJournal) { j.Schema += "x" },
		"confirmation": func(j *upgradeJournal) { j.Confirmation = strings.Repeat("0", 64) },
		"baseline":     func(j *upgradeJournal) { j.Baseline = strings.Repeat("0", 64) },
		"old-bytes":    func(j *upgradeJournal) { j.OriginalPlan = []byte("{}") },
		"restored":     func(j *upgradeJournal) { j.RestoredStateHash = strings.Repeat("0", 64) },
		"target":       func(j *upgradeJournal) { j.TargetStateHash = strings.Repeat("0", 64) },
		"unit":         func(j *upgradeJournal) { j.Intent.UnitPath += ".other" },
		"state":        func(j *upgradeJournal) { j.Intent.StatePath += ".other" },
		"tenant":       func(j *upgradeJournal) { j.Intent.TenantID += ".other" },
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			copy := *j
			mutate(&copy)
			if name == "unit" || name == "state" || name == "tenant" {
				copy.Confirmation, _ = copy.Intent.digest()
			}
			if _, err := copy.inspect(context.Background(), f.verifier); err == nil {
				t.Fatal("changed binding accepted")
			}
		})
	}
}

func TestUpgradeJournalPersistsAcrossProcessExit(t *testing.T) {
	f := newUpgradeFixture(t)
	review, err := inspectUpgrade(context.Background(), f.o, func() time.Time { return f.now }, f.verifier)
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(os.Args[0], "-test.run=^TestUpgradeJournalProcessHelper$")
	cmd.Env = append(os.Environ(), "SIQ_TEST_UPGRADE_PROCESS=create", "SIQ_TEST_UPGRADE_ROOT="+f.root, "SIQ_TEST_UPGRADE_CONFIRM="+review.Confirmation)
	if err := cmd.Run(); err == nil || cmd.ProcessState.ExitCode() != 73 {
		t.Fatal("expected abrupt exit after durable prepare", err)
	}
	if _, err := readUpgradeJournal(context.Background(), f.verifier); err != nil {
		t.Fatal("fresh process lost pending record", err)
	}
	cmd = exec.Command(os.Args[0], "-test.run=^TestUpgradeJournalProcessHelper$")
	cmd.Env = append(os.Environ(), "SIQ_TEST_UPGRADE_PROCESS=blocked")
	if err := cmd.Run(); err == nil || cmd.ProcessState.ExitCode() != 74 {
		t.Fatal("fresh task process not blocked", err)
	}
}

func TestUpgradeJournalProcessHelper(t *testing.T) {
	switch os.Getenv("SIQ_TEST_UPGRADE_PROCESS") {
	case "create":
		root := os.Getenv("SIQ_TEST_UPGRADE_ROOT")
		plan, err := readInstallDocument(filepath.Join(root, "new-plan.json"))
		if err != nil {
			os.Exit(80)
		}
		parsed, err := installplan.Parse(plan)
		if err != nil {
			os.Exit(81)
		}
		f := &upgradeFixture{o: upgradeReviewOptions{from: filepath.Join(root, "old-stage"), to: filepath.Join(root, "new-stage"), plan: filepath.Join(root, "new-plan.json"), tenant: parsed.TenantID}}
		unlock, err := acquireRawTaskLock()
		if err != nil {
			os.Exit(82)
		}
		defer unlock()
		if _, err := prepareUpgradeJournal(context.Background(), f.o, os.Getenv("SIQ_TEST_UPGRADE_CONFIRM"), time.Now, f.verifier); err != nil {
			os.Exit(83)
		}
		os.Exit(73) // No deferred unlock or cleanup: kernel releases flock.
	case "blocked":
		if errors.Is(cmdTasks(context.Background(), nil), errUpgradePending) {
			os.Exit(74)
		}
		os.Exit(84)
	}
}

func TestUpgradeTaskLockPinsAncestorsAndLoadsStateOnlyAfterLock(t *testing.T) {
	f := newUpgradeFixture(t)
	unlock, err := acquireRawTaskLock()
	if err != nil {
		t.Fatal(err)
	}
	defer unlock()
	path, _ := StateFilePath()
	if os.WriteFile(path, []byte("invalid-state"), 0600) != nil {
		t.Fatal("fixture")
	}
	for _, run := range []func(context.Context, []string) error{cmdTasks, cmdServe} {
		if err := run(context.Background(), nil); err == nil || err.Error() != "edge task runner already active" {
			t.Fatal("state loaded before lock", err)
		}
	}
	alias := filepath.Join(f.root, "state-alias")
	if os.Symlink(filepath.Join(f.root, "state"), alias) != nil {
		t.Fatal("fixture")
	}
	t.Setenv("SIQ_EDGE_STATE_DIR", alias)
	if release, err := acquireRawTaskLock(); err == nil {
		release()
		t.Fatal("linked state directory accepted")
	}
}

func TestUpgradeTaskLockRejectsWritableAncestor(t *testing.T) {
	f := newUpgradeFixture(t)
	if err := os.Chmod(f.root, 0775); err != nil {
		t.Fatal(err)
	}
	defer os.Chmod(f.root, 0700)
	if release, err := acquireRawTaskLock(); err == nil {
		release()
		t.Fatal("writable ancestor accepted")
	}
	if _, err := os.Lstat(filepath.Join(f.root, "state", "tasks.lock")); !os.IsNotExist(err) {
		t.Fatal("unsafe path created lock")
	}
}
