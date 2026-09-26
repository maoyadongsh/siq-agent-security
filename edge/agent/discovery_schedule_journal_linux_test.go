//go:build linux

package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func scheduleJournalFixture(t *testing.T) (*State, []byte, time.Time) {
	t.Helper()
	parent := t.TempDir()
	if os.Chmod(parent, 0700) != nil {
		t.Fatal("private fixture")
	}
	t.Setenv("SIQ_EDGE_STATE_DIR", filepath.Join(parent, "private"))
	state, schedule, now := scheduleFixture(t)
	state.Secret = "edge-synthetic-private-credential-for-test"
	if err := state.Save(); err != nil {
		t.Fatal(err)
	}
	raw, err := json.Marshal(schedule)
	if err != nil {
		t.Fatal(err)
	}
	return state, raw, now
}

func TestScheduleJournalDurableExclusiveAndExactRecovery(t *testing.T) {
	state, raw, now := scheduleJournalFixture(t)
	unlock, err := acquireTaskLock()
	if err != nil {
		t.Fatal(err)
	}
	defer unlock()
	journal, err := prepareScheduleJournal(state, raw, 0, true, now)
	if err != nil {
		t.Fatal(err)
	}
	path, _ := scheduleJournalPath()
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	info, _ := os.Stat(path)
	if info.Mode().Perm() != 0600 || strings.Contains(string(before), state.Secret) || strings.Contains(string(before), state.SignerSeed) {
		t.Fatal("secret or permissions leaked")
	}
	if _, err := prepareScheduleJournal(state, raw, 0, true, now.Add(time.Minute)); err == nil {
		t.Fatal("overwrote journal")
	}
	after, _ := os.ReadFile(path)
	if string(before) != string(after) {
		t.Fatal("changed original request")
	}
	recovered, err := readScheduleJournal(state)
	if err != nil || recovered.Request != journal.Request {
		t.Fatal("recovery changed request")
	}
	rotated := *state
	rotated.Secret = "different-synthetic-credential"
	if _, err := readScheduleJournal(&rotated); err != nil {
		t.Fatal("credential rotation invalidated unchanged signing identity")
	}
}

func TestScheduleJournalNoWriteWithoutConsentOrMatchingState(t *testing.T) {
	for _, fault := range []string{"unconfirmed", "state", "scope", "legacy"} {
		t.Run(fault, func(t *testing.T) {
			state, raw, now := scheduleJournalFixture(t)
			confirmed := true
			switch fault {
			case "unconfirmed":
				confirmed = false
			case "state":
				state.EnvironmentID = "foreign"
			case "scope":
				raw = []byte(strings.Replace(string(raw), `"max_runs":4`, `"max_runs":0`, 1))
			case "legacy":
				state.DiscoveryPlan = nil
				state.DiscoveryPlanSHA256 = ""
			}
			if _, err := prepareScheduleJournal(state, raw, 0, confirmed, now); err == nil {
				t.Fatal("unsafe journal created")
			}
			path, _ := scheduleJournalPath()
			if _, err := os.Lstat(path); !os.IsNotExist(err) {
				t.Fatal("unexpected file")
			}
		})
	}
}

func TestScheduleJournalRejectsUnsafeFilesAndTampering(t *testing.T) {
	for _, fault := range []string{"mode", "symlink", "hardlink", "partial", "duplicate", "alias", "request", "intent", "oversize", "baseline"} {
		t.Run(fault, func(t *testing.T) {
			state, raw, now := scheduleJournalFixture(t)
			journal, err := prepareScheduleJournal(state, raw, 0, true, now)
			if err != nil {
				t.Fatal(err)
			}
			path, _ := scheduleJournalPath()
			original, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			changed := original
			switch fault {
			case "mode":
				err = os.Chmod(path, 0644)
			case "symlink", "hardlink":
				other := filepath.Join(filepath.Dir(path), "test-owned-original.json")
				err = os.Rename(path, other)
				if err != nil {
					t.Fatal(err)
				}
				if fault == "symlink" {
					err = os.Symlink(other, path)
				} else {
					err = os.Link(other, path)
				}
			case "partial":
				changed = []byte(`{"schema_version":`)
			case "duplicate":
				changed = []byte(strings.TrimSuffix(string(original), "}") + `,"schema_version":"edge-discovery-schedule-pending/v1"}`)
			case "alias":
				changed = []byte(strings.Replace(string(original), `"state_baseline"`, `"STATE_BASELINE"`, 1))
			case "request":
				journal.Request.Origin = "https://foreign.example.test"
				changed, err = json.Marshal(journal)
			case "intent":
				journal.Intent = []byte(strings.Replace(string(raw), `"max_runs":4`, `"max_runs":5`, 1))
				changed, err = json.Marshal(journal)
			case "oversize":
				changed = []byte(strings.Repeat(" ", 16385))
			case "baseline":
				journal.Baseline = strings.Repeat("f", 64)
				changed, err = json.Marshal(journal)
			}
			if err != nil {
				t.Fatal(err)
			}
			if string(changed) != string(original) {
				if err := os.WriteFile(path, changed, 0600); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := readScheduleJournal(state); err == nil {
				t.Fatal("unsafe journal accepted")
			}
		})
	}
}
