//go:build linux

package main

import (
	"errors"
	"os"
	"reflect"
	"strings"
	"testing"
)

func TestRotationActivationFilesystemFailures(t *testing.T) {
	for _, stage := range []string{"save-before", "save-after", "save-noop", "sync-state", "remove", "sync-cleanup", "success"} {
		t.Run(stage, func(t *testing.T) {
			state := journalFixture(t)
			journal, err := prepareRotationJournal(state)
			if err != nil {
				t.Fatal(err)
			}
			fault := errors.New("simulated-disk-error " + journal.NewSecret)
			var operations []string
			syncCalls := 0
			files := rotationFileOps{
				save: func(s *State) error {
					operations = append(operations, "save")
					if stage == "save-before" {
						return fault
					}
					if stage == "save-noop" {
						return nil
					}
					if err := s.Save(); err != nil {
						return err
					}
					if stage == "save-after" {
						return fault
					}
					return nil
				},
				syncDir: func(path string) error {
					syncCalls++
					operations = append(operations, "sync")
					if (stage == "sync-state" && syncCalls == 1) || (stage == "sync-cleanup" && syncCalls == 2) {
						return fault
					}
					return syncRegistrationDirectory(path)
				},
				remove: func(path string) error {
					operations = append(operations, "remove")
					if stage == "remove" {
						return fault
					}
					return os.Remove(path)
				},
			}
			err = activateRotation(state, journal, files)
			if stage == "success" {
				if err != nil {
					t.Fatal(err)
				}
			} else if err == nil || strings.Contains(err.Error(), journal.NewSecret) {
				t.Fatal("failure lost or secret leaked")
			}
			if stage == "sync-cleanup" && err != errRotationCleanup {
				t.Fatal("cleanup failure mistaken for unknown activation")
			}
			expectedOps := map[string][]string{
				"save-before": {"save"}, "save-after": {"save"}, "sync-state": {"save", "sync"},
				"save-noop": {"save", "sync"},
				"remove":    {"save", "sync", "remove"}, "sync-cleanup": {"save", "sync", "remove", "sync"}, "success": {"save", "sync", "remove", "sync"},
			}[stage]
			if !reflect.DeepEqual(operations, expectedOps) {
				t.Fatal("unsafe operation ordering", operations)
			}
			current, err := loadRotationState()
			if err != nil {
				t.Fatal(err)
			}
			expectedSecret := journal.NewSecret
			if stage == "save-before" || stage == "save-noop" {
				expectedSecret = state.Secret
			}
			if current.Secret != expectedSecret || rotationStateBaseline(current) != rotationStateBaseline(state) {
				t.Fatal("state corrupted")
			}
			if stage == "success" || stage == "sync-cleanup" {
				path, _ := rotationJournalPath()
				if _, err := os.Lstat(path); !os.IsNotExist(err) {
					t.Fatal("journal should be removed after activation")
				}
			} else {
				pending, err := readRotationJournal(current)
				if err != nil || *pending != *journal {
					t.Fatal("recovery evidence lost")
				}
				// A later confirmed recovery may finish from either old or new state.
				if err := activateRotation(current, pending, rotationFileOps{save: (*State).Save, syncDir: syncRegistrationDirectory, remove: os.Remove}); err != nil {
					t.Fatal("cannot finish after fault", err)
				}
			}
		})
	}
}
