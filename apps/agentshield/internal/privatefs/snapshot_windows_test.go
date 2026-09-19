package privatefs

import (
	"encoding/binary"
	"errors"
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func snapshotFixtureFile(t *testing.T, dir, name string) string {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := MkdirAll(filepath.Dir(path)); err != nil {
		t.Fatal(err)
	}
	f, err := CreateNew(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = f.WriteString("fixed metadata"); err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestWindowsReadSnapshotRejectsReparseAndExistingWriter(t *testing.T) {
	dir := privateFixture(t)
	target := privateFixture(t)
	snapshotFixtureFile(t, target, "done.json")
	link := filepath.Join(dir, "junction")
	if err := os.Mkdir(link, 0700); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := os.Remove(link); err != nil {
			t.Error(err)
		}
	})
	sub, err := syscall.UTF16FromString(`\??\` + target)
	if err != nil {
		t.Fatal(err)
	}
	printed, err := syscall.UTF16FromString(target)
	if err != nil {
		t.Fatal(err)
	}
	data := make([]byte, 16+2*(len(sub)+len(printed)))
	binary.LittleEndian.PutUint32(data, 0xa0000003)
	binary.LittleEndian.PutUint16(data[4:], uint16(len(data)-8))
	binary.LittleEndian.PutUint16(data[10:], uint16((len(sub)-1)*2))
	binary.LittleEndian.PutUint16(data[12:], uint16(len(sub)*2))
	binary.LittleEndian.PutUint16(data[14:], uint16((len(printed)-1)*2))
	for i, v := range append(sub, printed...) {
		binary.LittleEndian.PutUint16(data[16+i*2:], v)
	}
	name, _ := syscall.UTF16PtrFromString(link)
	h, err := syscall.CreateFile(name, syscall.GENERIC_WRITE, 0, nil, syscall.OPEN_EXISTING, syscall.FILE_FLAG_OPEN_REPARSE_POINT|syscall.FILE_FLAG_BACKUP_SEMANTICS, 0)
	if err != nil {
		t.Fatal(err)
	}
	var returned uint32
	err = syscall.DeviceIoControl(h, 0x000900a4, &data[0], uint32(len(data)), nil, 0, &returned, nil)
	syscall.CloseHandle(h)
	if err != nil {
		t.Fatal(err)
	}
	if s, err := OpenReadSnapshot(link); err == nil {
		s.Close()
		t.Fatal("reparse root accepted")
	}
	s, err := OpenReadSnapshot(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.ReadFile(filepath.Join("junction", "done.json"), 128); err == nil {
		t.Fatal("reparse child accepted")
	}
	s.Close()
	path := snapshotFixtureFile(t, dir, "mutable.json")
	writer, err := os.OpenFile(path, os.O_RDWR, 0600)
	if err != nil {
		t.Fatal(err)
	}
	defer writer.Close()
	s, err = OpenReadSnapshot(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if _, err := s.ReadFile("mutable.json", 128); err == nil {
		t.Fatal("existing writer bypassed coherent read")
	}
}

func TestWindowsReadSnapshotPinsAndRechecks(t *testing.T) {
	dir := privateFixture(t)
	path := snapshotFixtureFile(t, dir, filepath.Join("proof", "done.json"))
	s, err := OpenReadSnapshot(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	name := filepath.Join("proof", "done.json")
	if raw, err := s.ReadFile(name, 128); err != nil || string(raw) != "fixed metadata" {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("replacement"), 0600); err == nil {
		t.Fatal("live metadata write was not excluded")
	}
	if err := os.Rename(path, path+"-moved"); err == nil {
		t.Fatal("live metadata replacement was not excluded")
	}
	if err := os.Rename(filepath.Dir(path), filepath.Dir(path)+"-moved"); err == nil {
		t.Fatal("live parent replacement was not excluded")
	}
	for _, directory := range []string{dir, filepath.Dir(path)} {
		name, _ := syscall.UTF16PtrFromString(directory)
		h, err := syscall.CreateFile(name, syscall.GENERIC_WRITE, syscall.FILE_SHARE_READ|syscall.FILE_SHARE_WRITE|syscall.FILE_SHARE_DELETE, nil, syscall.OPEN_EXISTING, syscall.FILE_FLAG_OPEN_REPARSE_POINT|syscall.FILE_FLAG_BACKUP_SEMANTICS, 0)
		if err == nil {
			syscall.CloseHandle(h)
			t.Fatal("live directory reparse writer was not excluded")
		}
		if !errors.Is(err, syscall.Errno(32)) { // ERROR_SHARING_VIOLATION
			t.Fatal("directory writer failed for an unrelated reason", err)
		}
	}
	if err := s.Verify(); err != nil {
		t.Fatal(err)
	}
	if _, err := s.ReadFile(name, 3); err == nil {
		t.Fatal("reused handle bypassed read bound")
	}
	if _, err := s.ReadFile(filepath.Join("..", "foreign"), 128); err == nil {
		t.Fatal("escaped root")
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("new metadata"), 0600); err != nil {
		t.Fatal(err)
	}
	next, err := OpenReadSnapshot(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer next.Close()
	if raw, err := next.ReadFile(name, 128); err != nil || string(raw) != "new metadata" {
		t.Fatal("new call reused stale bytes", err)
	}
}

func TestWindowsReadSnapshotRejectsACLDriftAndHardLinks(t *testing.T) {
	for _, target := range []string{"file", "directory"} {
		t.Run(target, func(t *testing.T) {
			dir := privateFixture(t)
			path := snapshotFixtureFile(t, dir, filepath.Join("proof", "done.json"))
			s, err := OpenReadSnapshot(dir)
			if err != nil {
				t.Fatal(err)
			}
			defer s.Close()
			if _, err := s.ReadFile(filepath.Join("proof", "done.json"), 128); err != nil {
				t.Fatal(err)
			}
			sid, err := currentSID()
			if err != nil {
				t.Fatal(err)
			}
			changed := path
			if target == "directory" {
				changed = filepath.Dir(path)
			}
			fixtureACL(t, changed, "D:P(A;OICI;FA;;;"+sid+")(A;OICI;GR;;;WD)")
			defer fixtureACL(t, changed, "D:P(A;OICI;FA;;;"+sid+")")
			if err := s.Verify(); !errors.Is(err, ErrPrivate) {
				t.Fatal("live ACL expansion accepted", err)
			}
		})
	}
	dir := privateFixture(t)
	path := snapshotFixtureFile(t, dir, "done.json")
	if err := os.Link(path, path+"-alias"); err != nil {
		t.Fatal(err)
	}
	s, err := OpenReadSnapshot(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if _, err := s.ReadFile("done.json", 128); !errors.Is(err, ErrPrivate) {
		t.Fatal("hard-linked metadata accepted", err)
	}
}
