//go:build linux

package main

import (
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

func TestDeviceStateReadRejectsUnsafeFilesWithoutRepair(t *testing.T) {
	for _, kind := range []string{"public-file", "public-dir", "symlink", "parent-link", "hardlink", "fifo", "duplicate", "oversize"} {
		t.Run(kind, func(t *testing.T) {
			dir := t.TempDir()
			_ = os.Chmod(dir, 0700)
			t.Setenv("SIQ_EDGE_STATE_DIR", dir)
			state := &State{DeviceIdentity: "fixture", Secret: "fixture-private"}
			if err := state.Save(); err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(dir, "state.json")
			var err error
			switch kind {
			case "public-file":
				err = os.Chmod(path, 0644)
			case "public-dir":
				err = os.Chmod(dir, 0755)
			case "symlink", "fifo":
				err = os.Rename(path, filepath.Join(dir, "preserved.json"))
				if err != nil {
					t.Fatal(err)
				}
				if kind == "symlink" {
					err = os.Symlink(filepath.Join(dir, "preserved.json"), path)
				} else {
					err = syscall.Mkfifo(path, 0600)
				}
			case "parent-link":
				link := filepath.Join(t.TempDir(), "linked")
				err = os.Symlink(dir, link)
				t.Setenv("SIQ_EDGE_STATE_DIR", link)
			case "hardlink":
				err = os.Link(path, filepath.Join(dir, "extra.json"))
			case "duplicate":
				err = os.WriteFile(path, []byte(`{"device_identity":"fixture","secret":"one","secret":"two"}`), 0600)
			case "oversize":
				err = os.WriteFile(path, []byte(strings.Repeat("x", 1<<20)), 0600)
			}
			if err != nil {
				t.Fatal(err)
			}
			if _, err := LoadState(); err == nil || strings.Contains(err.Error(), dir) || strings.Contains(err.Error(), "fixture-private") {
				t.Fatal("unsafe state accepted or error leaked", err)
			}
			if _, err := os.Lstat(path); err != nil {
				t.Fatal("state deleted", err)
			}
		})
	}
}

func TestDeviceStateReadPrivateRoundTripAndMissing(t *testing.T) {
	dir := t.TempDir()
	_ = os.Chmod(dir, 0700)
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	if _, err := LoadState(); err != ErrNotRegistered {
		t.Fatal(err)
	}
	s := &State{DeviceIdentity: "fixture", Secret: "synthetic-secret"}
	if err := s.Save(); err != nil {
		t.Fatal(err)
	}
	got, err := LoadState()
	if err != nil || got.Secret != s.Secret || got.DeviceIdentity != s.DeviceIdentity {
		t.Fatal("private roundtrip failed", err)
	}
	t.Setenv("SIQ_EDGE_STATE_DIR", "relative")
	if _, err := LoadState(); err == nil {
		t.Fatal("relative identity directory accepted")
	}
}
