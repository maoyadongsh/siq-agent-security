package skillinstall

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
	"unicode/utf8"
)

func TestDarwinSkillUnicodeCasePermissionClockAndOccupancy(t *testing.T) {
	if runtime.GOOS != "darwin" {
		t.Skip("macOS APFS skill occupancy")
	}

	t.Run("unicode-filename-occupant", func(t *testing.T) {
		f := setupFiles(t, map[string]string{"café.md": "payload-nfc"})
		p, _, err := f.store.Stage(nil, f.request)
		if err != nil {
			t.Fatal(err)
		}
		request := ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, p.ActorID, true}
		target := filepath.Join(f.root, "skills", p.DirectoryName)
		nfd := filepath.Join(target, "cafe\u0301.md")
		f.store.boundary = func(phase string) error {
			if phase == "directory_created:" {
				write(t, nfd, "user-nfd")
			}
			return nil
		}
		result, err := f.store.Apply(nil, request)
		kept, readErr := os.ReadFile(nfd)
		if readErr != nil {
			// Default APFS may surface the occupant under the NFC spelling.
			kept, readErr = os.ReadFile(filepath.Join(target, "café.md"))
		}
		if readErr != nil || string(kept) != "user-nfd" {
			if result != nil && result.Status == "installed_unverified" {
				t.Fatal("unicode occupant replaced by payload", readErr, result)
			}
			if _, statErr := os.Stat(nfd); statErr != nil && !utf8.ValidString(nfd) {
				t.Fatal(statErr)
			}
		}
		if err == nil && result != nil && result.Status == "installed_unverified" {
			t.Fatal("install claimed success over a Unicode-aliased occupant")
		}
		if result != nil && result.Status == "recovery_required" {
			if string(kept) != "user-nfd" {
				t.Fatal("recovery deleted unicode occupant")
			}
		}
	})

	t.Run("case-alias-directory", func(t *testing.T) {
		f, p, request := readyInstall(t)
		f.store.boundary = func(phase string) error {
			if phase == "spooled" {
				write(t, filepath.Join(f.root, "skills", strings.ToUpper(p.DirectoryName), "user.txt"), "keep")
			}
			return nil
		}
		result, err := f.store.Apply(nil, request)
		raw, _ := os.ReadFile(filepath.Join(f.root, "skills", strings.ToUpper(p.DirectoryName), "user.txt"))
		if string(raw) != "keep" {
			t.Fatal("case alias overwritten")
		}
		if err == nil {
			t.Fatal("case-alias install accepted")
		}
		if result == nil {
			t.Fatal("case-alias failure unrecorded")
		}
		if caseInsensitiveDir(t, f.root) && result.Status != "recovery_required" {
			t.Fatal("APFS case alias was not left for recovery", result)
		}
	})

	t.Run("permission-denied-parent", func(t *testing.T) {
		f, p, request := readyInstall(t)
		parent := filepath.Join(f.root, "skills")
		if err := os.MkdirAll(parent, 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.Chmod(parent, 0555); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = os.Chmod(parent, 0700) })
		result, err := f.store.Apply(nil, request)
		if err == nil {
			t.Fatal("install into chmod 0555 skills directory succeeded")
		}
		if result != nil && result.Status == "installed_unverified" {
			t.Fatal(result)
		}
		if entries, _ := os.ReadDir(parent); len(entries) != 0 {
			t.Fatal("permission failure left owned install files", entries)
		}
		_ = p
	})

	t.Run("clock-expiry", func(t *testing.T) {
		f, p, request := readyInstall(t)
		end, err := time.Parse(time.RFC3339Nano, p.ExpiresAt)
		if err != nil {
			t.Fatal(err)
		}
		f.store.now = func() time.Time { return end.Add(time.Second) }
		result, err := f.store.Apply(nil, request)
		if err == nil || (result != nil && result.Status == "installed_unverified") {
			t.Fatal("expired plan installed after clock warp", result, err)
		}
		if result != nil && result.Status == "rolled_back" {
			if _, statErr := os.Stat(filepath.Join(f.root, "skills", p.DirectoryName)); !os.IsNotExist(statErr) {
				t.Fatal("expired apply left owned target", statErr)
			}
		}
	})

	t.Run("occupied-directory-after-first-file", func(t *testing.T) {
		f := setupFiles(t, map[string]string{"notes.md": "keep-notes"})
		p, _, err := f.store.Stage(nil, f.request)
		if err != nil {
			t.Fatal(err)
		}
		request := ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, p.ActorID, true}
		target := filepath.Join(f.root, "skills", p.DirectoryName)
		locked := false
		f.store.boundary = func(phase string) error {
			if strings.HasPrefix(phase, "file_published:") && !locked {
				locked = true
				if err := os.Chmod(target, 0555); err != nil {
					t.Fatal(err)
				}
			}
			return nil
		}
		t.Cleanup(func() { _ = os.Chmod(target, 0700) })
		result, err := f.store.Apply(nil, request)
		_ = os.Chmod(target, 0700)
		if err == nil && result != nil && result.Status == "installed_unverified" {
			t.Fatal("install finished after directory was made non-writable")
		}
		if result != nil && result.Status == "recovery_required" {
			return
		}
		if _, statErr := os.Stat(target); statErr == nil {
			entries, _ := os.ReadDir(target)
			for _, e := range entries {
				if e.Name() == "user.txt" {
					t.Fatal("unknown occupant invented during occupancy failure")
				}
			}
		}
	})

	t.Run("revoke-during-publish", func(t *testing.T) {
		f, p, request := readyInstall(t)
		target := filepath.Join(f.root, "skills", p.DirectoryName)
		f.store.boundary = func(phase string) error {
			if strings.HasPrefix(phase, "file_published:") {
				f.revoke(t)
				return errors.New("interrupted after revoke")
			}
			return nil
		}
		result, err := f.store.Apply(nil, request)
		if err == nil || result == nil || result.Status != "rolled_back" {
			t.Fatal("revoke window retained install", result, err)
		}
		if _, err := os.Stat(target); !os.IsNotExist(err) {
			t.Fatal("revoked install left owned target")
		}
	})
}
