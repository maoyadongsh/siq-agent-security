package privatefs

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"unsafe"
)

// Only this test helper changes ACLs, only on fresh per-test fixtures.
func fixtureACL(t *testing.T, path, sddl string) {
	t.Helper()
	native, err := nativePath(path)
	if err != nil {
		t.Fatal(err)
	}
	name, err := syscall.UTF16PtrFromString(native)
	if err != nil {
		t.Fatal(err)
	}
	err = withDescriptor(sddl, func(sa *syscall.SecurityAttributes) error {
		ok, _, err := advapi.NewProc("SetFileSecurityW").Call(uintptr(unsafe.Pointer(name)), 4|0x80000000, sa.SecurityDescriptor)
		if ok == 0 {
			return err
		}
		return nil
	})
	if err != nil {
		t.Fatal("fixture ACL failed", err)
	}
}

func privateFixture(t *testing.T) string {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "private")
	if err := MkdirAll(dir); err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestWindowsPrivateCreateUnderBroadParent(t *testing.T) {
	parent := t.TempDir()
	sid, err := currentSID()
	if err != nil {
		t.Fatal(err)
	}
	fixtureACL(t, parent, "D:P(A;OICI;FA;;;"+sid+")(A;OICI;GR;;;WD)")
	if err := CheckDir(parent); !errors.Is(err, ErrPrivate) {
		t.Fatal("broad parent accepted")
	}
	dir := filepath.Join(parent, "state", "keys")
	if err := MkdirAll(dir); err != nil {
		t.Fatal(err)
	}
	if err := CheckDir(filepath.Dir(dir)); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "secret")
	f, err := CreateNew(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := CheckFile(f); err != nil {
		t.Fatal("new file unsafe before first write", err)
	}
	if _, err = f.WriteString("public synthetic secret"); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	b, err := ReadFile(path, 128)
	if err != nil || string(b) != "public synthetic secret" {
		t.Fatal("private read failed", err)
	}
	if _, err := CreateNew(path); !errors.Is(err, os.ErrExist) {
		t.Fatal("existing secret not exclusive", err)
	}
	if b, err := ReadFile(path, 128); err != nil || string(b) != "public synthetic secret" {
		t.Fatal("existing secret mutated")
	}
	// Privacy is supplied by the new object's descriptor, not parent repair.
	if err := CheckDir(parent); !errors.Is(err, ErrPrivate) {
		t.Fatal("broad ambient parent unexpectedly repaired")
	}
}

func TestWindowsPrivateReadRejectsACLWithoutRepair(t *testing.T) {
	sid, err := currentSID()
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct{ name, sddl string }{
		{"everyone-read", "D:P(A;;FA;;;" + sid + ")(A;;GR;;;WD)"},
		{"authenticated-users", "D:P(A;;FA;;;" + sid + ")(A;;GR;;;AU)"},
		{"builtin-users", "D:P(A;;FA;;;" + sid + ")(A;;GR;;;BU)"},
		{"untrusted-write", "D:P(A;;FA;;;" + sid + ")(A;;GW;;;WD)"},
		{"null-dacl", "D:NO_ACCESS_CONTROL"},
		{"empty-dacl", "D:P"},
		{"deny-current", "D:P(D;;GR;;;" + sid + ")(A;;FA;;;" + sid + ")"},
		{"unknown-object-ace", "D:P(A;;FA;;;" + sid + ")(OA;;GR;11111111-1111-1111-1111-111111111111;;" + sid + ")"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := privateFixture(t)
			path := filepath.Join(dir, "seed")
			raw := []byte("fixed public fixture")
			f, err := CreateNew(path)
			if err != nil {
				t.Fatal(err)
			}
			if _, err = f.Write(raw); err != nil {
				t.Fatal(err)
			}
			f.Close()
			fixtureACL(t, path, tc.sddl)
			if _, err := ReadFile(path, 128); !errors.Is(err, ErrPrivate) {
				t.Fatal("unsafe ACL accepted", err)
			}
			if _, err := ReadFile(path, 128); !errors.Is(err, ErrPrivate) {
				t.Fatal("read unexpectedly repaired ACL", err)
			}
			// Restore this known fixture only to verify its content and clean it.
			fixtureACL(t, path, "D:P(A;;FA;;;"+sid+")")
			b, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(b, raw) {
				t.Fatal("rejected read changed content")
			}
		})
	}
}

func TestWindowsPrivateSafeInheritanceAndLimits(t *testing.T) {
	dir := privateFixture(t)
	child := filepath.Join(dir, "inherited")
	if err := os.Mkdir(child, 0700); err != nil {
		t.Fatal(err)
	}
	if err := CheckDir(child); err != nil {
		t.Fatal("safe inherited ACL rejected", err)
	}
	path := filepath.Join(child, "inherited.secret")
	if err := os.WriteFile(path, []byte("safe"), 0600); err != nil {
		t.Fatal(err)
	}
	if b, err := ReadFile(path, 4); err != nil || string(b) != "safe" {
		t.Fatal(err)
	}
	if _, err := ReadFile(path, 3); !errors.Is(err, ErrPrivate) {
		t.Fatal("oversize private read accepted")
	}
	if err := os.Link(path, filepath.Join(child, "alias")); err != nil {
		t.Fatal(err)
	}
	if _, err := ReadFile(path, 128); !errors.Is(err, ErrPrivate) {
		t.Fatal("aliased secret accepted")
	}
}

func TestWindowsPrivateExistingDirectoryIsNotRepaired(t *testing.T) {
	dir := privateFixture(t)
	sid, err := currentSID()
	if err != nil {
		t.Fatal(err)
	}
	fixtureACL(t, dir, "D:P(A;OICI;FA;;;"+sid+")(A;OICI;GR;;;WD)")
	if err := MkdirAll(dir); !errors.Is(err, ErrPrivate) {
		t.Fatal("broad existing state accepted")
	}
	if _, err := CreateNew(filepath.Join(dir, "secret")); !errors.Is(err, ErrPrivate) {
		t.Fatal("secret created in broad existing state")
	}
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != 0 {
		t.Fatal("rejected directory mutated")
	}
	if err := CheckDir(dir); !errors.Is(err, ErrPrivate) {
		t.Fatal("existing ACL repaired")
	}
}

func TestWindowsPrivateLongUnicodePathAndTemp(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "中文 空格", strings.Repeat("deep", 30), strings.Repeat("long", 30))
	if err := MkdirAll(dir); err != nil {
		t.Fatal(err)
	}
	f, err := CreateTemp(dir, ".secret-*")
	if err != nil {
		t.Fatal(err)
	}
	name := f.Name()
	if err := CheckFile(f); err != nil {
		t.Fatal(err)
	}
	f.Close()
	if err := CheckFilePath(name); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{`\\server\share\secret`, `\\.\C:\secret`, `\\?\C:\secret`, filepath.Join(dir, "secret:stream"), filepath.Join(dir, "NUL"), filepath.Join(dir, "bad. ", "secret")} {
		if _, err := Open(path); err == nil {
			t.Fatal("nonlocal or namespace private path accepted")
		}
		if _, err := CreateNew(path); err == nil {
			t.Fatal("nonordinary private file created")
		}
	}
}
