package state

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestRecoveryCredentialIsPrivateIndependentAndPersistent(t *testing.T) {
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.ReadRecoveryToken(); !os.IsNotExist(err) {
		t.Fatal("read must not create credential")
	}
	decision, err := s.Token()
	if err != nil {
		t.Fatal(err)
	}
	recovery, err := s.RecoveryToken()
	if err != nil || len(recovery) != 64 || recovery == decision {
		t.Fatal("credential separation failed")
	}
	again, err := s.RecoveryToken()
	if err != nil || again != recovery {
		t.Fatal("credential changed across calls")
	}
	info, err := os.Stat(filepath.Join(s.Dir, recoveryFile))
	if err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" && info.Mode().Perm() != 0o600 {
		t.Fatal("credential permissions must be private")
	}
}

func TestRecoveryCredentialRefusesCorruptionAndSymlink(t *testing.T) {
	for _, value := range []string{"short", strings.Repeat("z", 64)} {
		s, _ := Open(t.TempDir())
		p := filepath.Join(s.Dir, recoveryFile)
		if err := os.WriteFile(p, []byte(value), 0o600); err != nil {
			t.Fatal(err)
		}
		if _, err := s.RecoveryToken(); err == nil {
			t.Fatal("corrupt credential accepted")
		}
		raw, _ := os.ReadFile(p)
		if string(raw) != value {
			t.Fatal("corrupt credential overwritten")
		}
	}
	if runtime.GOOS == "windows" {
		t.Skip("symlink creation requires OS privileges; covered on Unix")
	}
	s, _ := Open(t.TempDir())
	target := filepath.Join(s.Dir, "target")
	if err := os.WriteFile(target, []byte(strings.Repeat("a", 64)), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, filepath.Join(s.Dir, recoveryFile)); err != nil {
		t.Fatal(err)
	}
	if _, err := s.RecoveryToken(); err == nil {
		t.Fatal("symlink accepted")
	}
}
