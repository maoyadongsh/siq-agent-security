package effectevidence

import (
	"encoding/binary"
	"os"
	"path/filepath"
	"syscall"
	"testing"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func captureWindowsProfile(t *testing.T, path string) FileSnapshot {
	t.Helper()
	s, err := CaptureFileForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, path, 1024)
	if err != nil {
		t.Fatal("Windows component fixture rejected", err)
	}
	return s
}

func TestWindowsFileProfileLeafCreationAndReplacement(t *testing.T) {
	path := filepath.Join(t.TempDir(), "Output.txt")
	before := captureWindowsProfile(t, path)
	if before.Exists {
		t.Fatal("missing leaf reported present")
	}
	if err := os.WriteFile(path, []byte("first"), 0600); err != nil {
		t.Fatal(err)
	}
	created := captureWindowsProfile(t, path)
	if out, err := FileWrite(before, created, created.Digest); err != nil || out.Result != "expected" {
		t.Fatal("leaf creation rejected", err)
	}
	if err := os.WriteFile(path, []byte("updated"), 0600); err != nil {
		t.Fatal(err)
	}
	updated := captureWindowsProfile(t, path)
	if out, err := FileWrite(created, updated, updated.Digest); err != nil || out.Result != "expected" {
		t.Fatal("ordinary in-place write rejected", err)
	}
	// Keep content and mtime identical so the file identity is the only evidence
	// of replacement. Keeping the old object alive avoids NTFS file-ID reuse.
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(path, path+".previous"); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("updated"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(path, info.ModTime(), info.ModTime()); err != nil {
		t.Fatal(err)
	}
	replaced := captureWindowsProfile(t, path)
	if replaced.IdentityDigest == updated.IdentityDigest || replaced.ParentIdentityDigest != updated.ParentIdentityDigest {
		t.Fatal("leaf/parent identities not distinguished")
	}
	if out, err := FileWrite(updated, replaced, replaced.Digest); err != nil || out.Result != "expected" {
		t.Fatal("normal leaf replacement rejected", err)
	}
	if out, err := FileWrite(replaced, replaced, replaced.Digest); err != nil || out.Result != "unknown" {
		t.Fatal("unchanged file falsely proves write", err)
	}
}

func TestWindowsFileProfileParentReplacementRejected(t *testing.T) {
	parent := filepath.Join(t.TempDir(), "Parent")
	if err := os.Mkdir(parent, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(parent, "output.txt")
	before := captureWindowsProfile(t, path)
	if err := os.Rename(parent, parent+"-old"); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(parent, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("replacement"), 0600); err != nil {
		t.Fatal(err)
	}
	after := captureWindowsProfile(t, path)
	if before.ParentIdentityDigest == after.ParentIdentityDigest {
		t.Fatal("parent identity replacement not observed")
	}
	if _, err := FileWrite(before, after, after.Digest); err == nil {
		t.Fatal("same-path parent substitution accepted")
	}
}

func makeObservationJunction(t *testing.T, target, link string) {
	t.Helper()
	if err := os.Mkdir(link, 0700); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := os.Remove(link); err != nil {
			t.Error(err)
		}
	})
	sub, _ := syscall.UTF16FromString(`\??\` + target)
	printName, _ := syscall.UTF16FromString(target)
	data := make([]byte, 16+2*(len(sub)+len(printName)))
	binary.LittleEndian.PutUint32(data[0:], 0xa0000003)
	binary.LittleEndian.PutUint16(data[4:], uint16(len(data)-8))
	binary.LittleEndian.PutUint16(data[10:], uint16((len(sub)-1)*2))
	binary.LittleEndian.PutUint16(data[12:], uint16(len(sub)*2))
	binary.LittleEndian.PutUint16(data[14:], uint16((len(printName)-1)*2))
	for i, v := range append(sub, printName...) {
		binary.LittleEndian.PutUint16(data[16+i*2:], v)
	}
	p, _ := syscall.UTF16PtrFromString(link)
	h, err := syscall.CreateFile(p, syscall.GENERIC_WRITE, 0, nil, syscall.OPEN_EXISTING, syscall.FILE_FLAG_OPEN_REPARSE_POINT|syscall.FILE_FLAG_BACKUP_SEMANTICS, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer syscall.CloseHandle(h)
	var returned uint32
	if err := syscall.DeviceIoControl(h, 0x000900a4, &data[0], uint32(len(data)), nil, 0, &returned, nil); err != nil {
		t.Fatal(err)
	}
}

func TestWindowsFileProfileHardLinkAndReparseRejected(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "Actual.txt")
	if err := os.WriteFile(path, []byte("sentinel"), 0600); err != nil {
		t.Fatal(err)
	}
	linked := filepath.Join(dir, "hardlink.txt")
	if err := os.Link(path, linked); err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{path, linked} {
		if _, err := CaptureFileForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, p, 1024); err == nil {
			t.Fatal("hard link accepted", p)
		}
	}
	if err := os.Remove(linked); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(t.TempDir(), "redirect")
	makeObservationJunction(t, dir, link)
	for _, p := range []string{filepath.Join(link, "Actual.txt"), filepath.Join(link, "new.txt"), filepath.Join(dir, "actual.txt")} {
		if _, err := CaptureFileForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, p, 1024); err == nil {
			t.Fatal("reparse/case alias accepted", p)
		}
	}
	if raw, err := os.ReadFile(path); err != nil || string(raw) != "sentinel" {
		t.Fatal("capture modified target", err)
	}
}
