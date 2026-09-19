package state

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestWindowsStateCreatesPrivateRootUnderBroadParent(t *testing.T) {
	parent := t.TempDir()
	acltest.BroadenRead(t, parent, parent)
	if _, err := Open(parent); err == nil {
		t.Fatal("existing broad root accepted")
	}
	entries, err := os.ReadDir(parent)
	if err != nil || len(entries) != 0 {
		t.Fatal("rejected root mutated")
	}
	root := filepath.Join(parent, "state")
	s, err := Open(root)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := signing.Load(root); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Token(); err != nil {
		t.Fatal(err)
	}
	if _, err := s.RecoveryToken(); err != nil {
		t.Fatal(err)
	}
	if err := s.CheckPrivateCredentials(); err != nil {
		t.Fatal(err)
	}
	if err := privatefs.CheckDir(parent); err == nil {
		t.Fatal("ambient parent repaired")
	}
}

func TestWindowsSecretAccessRejectsBroadFilesWithoutReplacement(t *testing.T) {
	for _, name := range []string{"token", recoveryFile, "keys/signing.seed"} {
		t.Run(name, func(t *testing.T) {
			root := filepath.Join(t.TempDir(), "state")
			s, err := Open(root)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := signing.Load(root); err != nil {
				t.Fatal(err)
			}
			if _, err := s.Token(); err != nil {
				t.Fatal(err)
			}
			if _, err := s.RecoveryToken(); err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(root, filepath.FromSlash(name))
			before, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			acltest.BroadenRead(t, root, path)
			switch name {
			case "token":
				if _, err := s.Token(); err == nil {
					t.Fatal("broad token accepted")
				}
			case recoveryFile:
				if _, err := s.ReadRecoveryToken(); err == nil {
					t.Fatal("broad recovery token read")
				}
				if _, err := s.RecoveryToken(); err == nil {
					t.Fatal("broad recovery token reused")
				}
			default:
				if _, err := signing.Load(root); err == nil {
					t.Fatal("broad signing seed loaded")
				}
				if _, err := signing.LoadExisting(root); err == nil {
					t.Fatal("broad existing seed loaded")
				}
			}
			after, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(before, after) {
				t.Fatal("rejected secret replaced")
			}
			if err := privatefs.CheckFilePath(path); err == nil {
				t.Fatal("secret ACL implicitly repaired")
			}
		})
	}
}

func TestWindowsMigrationPrivateReadAndSnapshotRejectBroadState(t *testing.T) {
	root := filepath.Join(t.TempDir(), "state")
	s, err := Open(root)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.Token(); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "token")
	if _, err := snapshotMigration(root); err != nil {
		t.Fatal(err)
	}
	restore := acltest.BroadenRead(t, root, path)
	if _, err := snapshotMigration(root); err == nil {
		t.Fatal("unsafe secret entered backup")
	}
	if _, err := migrationReadRegular(path, 4096); err == nil {
		t.Fatal("unsafe secret reread for backup")
	}
	restore()
	if _, err := snapshotMigration(root); err != nil {
		t.Fatal("restored fixture rejected", err)
	}
	acltest.BroadenRead(t, root, filepath.Join(root, "backups"))
	if err := migrationPublish(root, filepath.Join(root, "backups", "secret"), []byte("public fixture"), 0600); err == nil {
		t.Fatal("published into broad backup directory")
	}
	entries, err := os.ReadDir(filepath.Join(root, "backups"))
	if err != nil || len(entries) != 0 {
		t.Fatal("rejected backup publication mutated directory")
	}
}
