//go:build linux

package main

import (
	"os"
	"path/filepath"
	"testing"
)

func journalFixture(t *testing.T) *State {
	t.Helper()
	parent := t.TempDir()
	if err := os.Chmod(parent, 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("SIQ_EDGE_STATE_DIR", filepath.Join(parent, "private"))
	state, _, _ := rotationFixture(t)
	state.ControlPlaneURL = "https://control.example.test"
	if err := state.Save(); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadState(); err != nil {
		t.Fatal("fixture state read:", err)
	}
	return state
}

func TestRotationJournalDurableAndExclusive(t *testing.T) {
	state := journalFixture(t)
	unlock, err := acquireTaskLock()
	if err != nil {
		t.Fatal(err)
	}
	defer unlock()
	journal, err := prepareRotationJournal(state)
	if err != nil {
		t.Fatal(err)
	}
	path, _ := rotationJournalPath()
	before, _ := os.ReadFile(path)
	info, _ := os.Stat(path)
	if info.Mode().Perm() != 0600 {
		t.Fatal("journal not private")
	}
	if _, err := prepareRotationJournal(state); err == nil {
		t.Fatal("overwrote pending request")
	}
	after, _ := os.ReadFile(path)
	if string(before) != string(after) {
		t.Fatal("pending request changed")
	}
	recovered, err := readRotationJournal(state)
	if err != nil || recovered.Request != journal.Request || recovered.NewSecret != journal.NewSecret {
		t.Fatal("cannot recover exact request")
	}
	loaded, err := LoadState()
	if err != nil || loaded.Secret != state.Secret {
		t.Fatal("preparation activated secret")
	}
	state.Secret = journal.NewSecret
	if _, err := readRotationJournal(state); err != nil {
		t.Fatal("cannot recover after activation")
	}
}

func TestRotationJournalRejectsStateAndRequestDrift(t *testing.T) {
	state := journalFixture(t)
	journal, err := prepareRotationJournal(state)
	if err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"environment", "identity", "url", "secret", "plan", "public-key", "signature", "new-secret"} {
		t.Run(field, func(t *testing.T) {
			s, j := *state, *journal
			switch field {
			case "environment":
				s.EnvironmentID = "different"
			case "identity":
				s.DeviceIdentity = "different"
			case "url":
				s.ControlPlaneURL = "https://foreign.example.test"
			case "secret":
				s.Secret = "different"
			case "plan":
				s.DiscoveryPlanSHA256 = "different"
			case "public-key":
				s.PublicKeyPEM = "different"
			case "signature":
				j.Request.Signature = "invalid"
			case "new-secret":
				j.NewSecret = "different"
			}
			if j.validate(&s) == nil {
				t.Fatal("accepted drift")
			}
		})
	}
}

func TestRotationJournalRejectsUnsafeFiles(t *testing.T) {
	for _, kind := range []string{"mode", "symlink", "hardlink", "partial", "duplicate", "oversize"} {
		t.Run(kind, func(t *testing.T) {
			state := journalFixture(t)
			if _, err := prepareRotationJournal(state); err != nil {
				t.Fatal(err)
			}
			path, _ := rotationJournalPath()
			switch kind {
			case "mode":
				if err := os.Chmod(path, 0644); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				target := filepath.Join(filepath.Dir(path), "saved-journal")
				if err := os.Rename(path, target); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(target, path); err != nil {
					t.Fatal(err)
				}
			case "hardlink":
				if err := os.Link(path, path+".link"); err != nil {
					t.Fatal(err)
				}
			case "partial":
				if err := os.WriteFile(path, []byte(`{"schema_version":`), 0600); err != nil {
					t.Fatal(err)
				}
			case "duplicate":
				if err := os.WriteFile(path, []byte(`{"schema_version":"a","schema_version":"b"}`), 0600); err != nil {
					t.Fatal(err)
				}
			case "oversize":
				if err := os.WriteFile(path, make([]byte, 8193), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := readRotationJournal(state); err == nil {
				t.Fatal("unsafe journal accepted")
			}
			if _, err := prepareRotationJournal(state); err == nil {
				t.Fatal("unsafe journal replaced")
			}
		})
	}
}
