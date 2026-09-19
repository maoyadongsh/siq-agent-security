package adapterinstall

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/privatefs"
)

func TestWindowsAdapterRecoveryPublicationPrivateAndExclusive(t *testing.T) {
	root := filepath.Join(t.TempDir(), "private")
	if err := privatefs.MkdirAll(root); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "adapter-transactions", "record.sealed")
	if err := publishRecoveryFile(path, []byte("private payload")); err != nil {
		t.Fatal(err)
	}
	if err := privatefs.CheckDir(filepath.Dir(path)); err != nil {
		t.Fatal(err)
	}
	if err := privatefs.CheckFilePath(path); err != nil {
		t.Fatal(err)
	}
	if err := publishRecoveryFile(path, []byte("replacement")); !errors.Is(err, os.ErrExist) {
		t.Fatal("exclusive conflict missing", err)
	}
	got, err := privateRead(path, 64)
	if err != nil || string(got) != "private payload" {
		t.Fatal("published payload changed", err)
	}
	acltest.BroadenRead(t, root, filepath.Dir(path))
	if err := publishRecoveryFile(filepath.Join(filepath.Dir(path), "second.sealed"), []byte("second")); err == nil {
		t.Fatal("wide parent accepted")
	}
	if _, err := os.Lstat(filepath.Join(filepath.Dir(path), "second.sealed")); !os.IsNotExist(err) {
		t.Fatal("rejected publication exposed output")
	}
}

func TestWindowsAdapterBackupKeyRejectsBroadACL(t *testing.T) {
	for _, target := range []string{"key", "root"} {
		t.Run(target, func(t *testing.T) {
			root := filepath.Join(t.TempDir(), "private")
			if err := privatefs.MkdirAll(root); err != nil {
				t.Fatal(err)
			}
			if _, err := backupAEAD(root, true); err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(root, "adapter-backup.key")
			before, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			changed := path
			if target == "root" {
				changed = root
			}
			acltest.BroadenRead(t, root, changed)
			for _, create := range []bool{false, true} {
				if _, err := backupAEAD(root, create); err == nil {
					t.Error("broad backup key accepted")
				}
			}
			after, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(before, after) {
				t.Fatal("backup key changed on rejection")
			}
			if target == "root" {
				if privatefs.CheckDir(changed) == nil {
					t.Fatal("root ACL repaired")
				}
			} else if privatefs.CheckFilePath(changed) == nil {
				t.Fatal("key ACL repaired")
			}
		})
	}
}

func TestWindowsAdapterPrivateRecoveryReadRejectsBroadACL(t *testing.T) {
	for _, target := range []string{"file", "parent"} {
		t.Run(target, func(t *testing.T) {
			root := filepath.Join(t.TempDir(), "private")
			if err := privatefs.MkdirAll(root); err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(root, "recovery.sealed")
			if err := publishFile(path, []byte("synthetic sealed recovery"), 0600, false); err != nil {
				t.Fatal(err)
			}
			if raw, err := privateRead(path, 64); err != nil || string(raw) != "synthetic sealed recovery" {
				t.Fatal("private baseline", err)
			}
			changed := path
			if target == "parent" {
				changed = root
			}
			acltest.BroadenRead(t, root, changed)
			if raw, err := privateRead(path, 64); err == nil || len(raw) != 0 {
				t.Fatal("broad recovery material read")
			}
		})
	}
}

func TestWindowsAdapterTransactionDirectoriesRejectBroadACL(t *testing.T) {
	for _, name := range []string{"adapter-transactions", "adapter-operations", "adapter-write"} {
		t.Run(name, func(t *testing.T) {
			opts := testOpts(t, Hermes)
			path := filepath.Join(opts.StateDir, name)
			if err := privatefs.MkdirAll(path); err != nil {
				t.Fatal(err)
			}
			acltest.BroadenRead(t, opts.StateDir, path)
			if _, err := Prepare(opts, "install"); err == nil {
				t.Fatal("broad operation directory accepted")
			}
			if privatefs.CheckDir(path) == nil {
				t.Fatal("operation ACL repaired")
			}
			if entries, err := os.ReadDir(path); err != nil || len(entries) != 0 {
				t.Fatal("operation directory changed")
			}
			if _, err := os.Lstat(filepath.Join(opts.Home, ".hermes")); !os.IsNotExist(err) {
				t.Fatal("host changed before refusal")
			}
		})
	}
}
