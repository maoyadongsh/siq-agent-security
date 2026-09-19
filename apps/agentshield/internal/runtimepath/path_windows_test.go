package runtimepath

import (
	"encoding/binary"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"unsafe"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func fixture(t *testing.T) (string, string) {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "中文 Space")
	if err := os.Mkdir(dir, 0700); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(dir, "ActualCase.txt")
	if err := os.WriteFile(file, []byte("sentinel"), 0600); err != nil {
		t.Fatal(err)
	}
	return dir, file
}

func TestWindowsLiveResourceAndMissingLeaf(t *testing.T) {
	dir, file := fixture(t)
	for _, path := range []string{dir, file} {
		s, err := InspectWindows(path, false)
		if err != nil {
			t.Fatalf("existing fixture rejected: %v", err)
		}
		if !s.Exists() || s.IsDirectory() != (path == dir) || s.Revalidate() != nil {
			t.Fatal("incorrect live facts")
		}
		canonical, _ := runtimeaction.NormalizeResourceForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, "filesystem", path)
		if s.Path() != canonical {
			t.Fatal("canonical name changed")
		}
	}
	missing := filepath.Join(dir, "new.txt")
	if _, err := InspectWindows(missing, false); err != ErrUnverified {
		t.Fatal("absent read accepted")
	}
	s, err := InspectWindows(missing, true)
	if err != nil || s.Exists() || s.IsDirectory() || s.Revalidate() != nil {
		t.Fatalf("new leaf: %v", err)
	}
	if _, err := os.Stat(missing); !os.IsNotExist(err) {
		t.Fatal("inspection created a file")
	}
	if err := os.WriteFile(missing, []byte("other writer"), 0600); err != nil {
		t.Fatal(err)
	}
	if s.Revalidate() != ErrUnverified {
		t.Fatal("newly present leaf accepted")
	}
	if _, err := InspectWindows(filepath.Join(dir, "missing-parent", "new.txt"), true); err != ErrUnverified {
		t.Fatal("unverified parent accepted")
	}
}

func TestWindowsResourceRejectsAliasesAndHardlinks(t *testing.T) {
	dir, file := fixture(t)
	for _, path := range []string{filepath.Join(dir, "actualcase.txt"), filepath.Join(dir, "ActualCase.txt.")} {
		if _, err := InspectWindows(path, false); err != ErrUnverified {
			t.Fatal("case or trailing-dot alias accepted")
		}
	}
	linked := filepath.Join(dir, "other.txt")
	if err := os.Link(file, linked); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{file, linked} {
		if _, err := runtimeaction.NormalizeResourceForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, "filesystem", path); err != nil {
			t.Fatal("fixture is not lexically valid")
		}
		if _, err := InspectWindows(path, false); err != ErrUnverified {
			t.Fatal("lexical success incorrectly treated as single-file identity")
		}
	}
	if err := os.Remove(linked); err != nil {
		t.Fatal(err)
	}
	s, err := InspectWindows(file, false)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Link(file, linked); err != nil {
		t.Fatal(err)
	}
	if s.Revalidate() != ErrUnverified {
		t.Fatal("link introduced after check accepted")
	}
}

func TestWindowsResourceRechecksParentAndTargetReplacement(t *testing.T) {
	for _, parent := range []bool{false, true} {
		name := "target"
		if parent {
			name = "parent"
		}
		t.Run(name, func(t *testing.T) {
			dir, file := fixture(t)
			s, err := InspectWindows(file, false)
			if err != nil {
				t.Fatal(err)
			}
			if parent {
				if err := os.Rename(dir, dir+"-old"); err != nil {
					t.Fatal(err)
				}
				if err := os.Mkdir(dir, 0700); err != nil {
					t.Fatal(err)
				}
			} else if err := os.Rename(file, file+"-old"); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(file, []byte("sentinel"), 0600); err != nil {
				t.Fatal(err)
			}
			if s.Revalidate() != ErrUnverified {
				t.Fatal("same-spelling replacement accepted")
			}
			if _, err := InspectWindows(file, false); err != nil {
				t.Fatal("new identity cannot be freshly inspected")
			}
		})
	}
}

func makeJunction(t *testing.T, target, link string) {
	t.Helper()
	if err := os.Mkdir(link, 0700); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := os.Remove(link); err != nil {
			t.Errorf("junction cleanup: %v", err)
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

func TestWindowsResourceRejectsRealJunction(t *testing.T) {
	dir, file := fixture(t)
	link := filepath.Join(filepath.Dir(dir), "redirect")
	makeJunction(t, dir, link)
	for _, path := range []string{link, filepath.Join(link, filepath.Base(file)), filepath.Join(link, "new.txt")} {
		if _, err := InspectWindows(path, true); err != ErrUnverified {
			t.Fatal("junction resource accepted")
		}
	}
	if got, err := os.ReadFile(file); err != nil || string(got) != "sentinel" {
		t.Fatal("target changed")
	}
}

func TestWindowsResourceRejectsShortName(t *testing.T) {
	_, file := fixture(t)
	p, _ := syscall.UTF16PtrFromString(file)
	var buffer [1024]uint16
	n, _, err := kernel.NewProc("GetShortPathNameW").Call(uintptr(unsafe.Pointer(p)), uintptr(unsafe.Pointer(&buffer[0])), uintptr(len(buffer)))
	if n == 0 || n >= uintptr(len(buffer)) {
		t.Fatalf("short name query: %v", err)
	}
	short := syscall.UTF16ToString(buffer[:n])
	if short == file {
		t.Skip("volume did not allocate an 8.3 name for this isolated fixture")
	}
	if _, err := InspectWindows(short, false); err != ErrUnverified {
		t.Fatal("short-name alias accepted")
	}
}

func TestWindowsResourceSharingConflictFailsClosed(t *testing.T) {
	_, file := fixture(t)
	s, err := InspectWindows(file, false)
	if err != nil {
		t.Fatal(err)
	}
	p, _ := syscall.UTF16PtrFromString(file)
	h, err := syscall.CreateFile(p, syscall.GENERIC_READ, 0, nil, syscall.OPEN_EXISTING, 0, 0)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.ReadFile(file); err == nil {
		t.Fatal("fixture did not exclude data reads")
	}
	if err := s.Revalidate(); err != ErrUnverified {
		t.Fatal("exclusive data handle did not prevent inspection")
	}
	if err := syscall.CloseHandle(h); err != nil {
		t.Fatal(err)
	}
	if s.Revalidate() != nil {
		t.Fatal("closed data handle changed identity")
	}
}

func TestWindowsResourceDeletePendingFailsClosed(t *testing.T) {
	_, file := fixture(t)
	s, err := InspectWindows(file, false)
	if err != nil {
		t.Fatal(err)
	}
	p, _ := syscall.UTF16PtrFromString(file)
	h, err := syscall.CreateFile(p, syscall.GENERIC_READ|0x10000, syscall.FILE_SHARE_READ|syscall.FILE_SHARE_WRITE|syscall.FILE_SHARE_DELETE, nil, syscall.OPEN_EXISTING, 0, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer syscall.CloseHandle(h)
	var disposition uint32 = 1
	ok, _, setErr := kernel.NewProc("SetFileInformationByHandle").Call(uintptr(h), 4, uintptr(unsafe.Pointer(&disposition)), unsafe.Sizeof(disposition))
	if ok == 0 {
		t.Fatalf("fixture deletion disposition: %v", setErr)
	}
	if _, err := InspectWindows(file, true); err != ErrUnverified {
		t.Fatal("delete-pending target treated as safe or absent")
	}
	if s.Revalidate() != ErrUnverified {
		t.Fatal("pending deletion accepted")
	}
}

func TestWindowsResourceReadHandlePinsRename(t *testing.T) {
	dir, file := fixture(t)
	for _, path := range []string{dir, file} {
		h, err := openComponent(path)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.Rename(path, path+"-moved"); err == nil {
			syscall.CloseHandle(h)
			t.Fatal("open resource name was not pinned")
		}
		if err := syscall.CloseHandle(h); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Rename(file, file+"-moved"); err != nil {
		t.Fatal("inspection leaked a pinning handle")
	}
}

func TestWindowsResourceCaseSensitiveDirectory(t *testing.T) {
	dir := t.TempDir()
	p, _ := syscall.UTF16PtrFromString(dir)
	h, err := syscall.CreateFile(p, 0x100|0x80, syscall.FILE_SHARE_READ|syscall.FILE_SHARE_WRITE, nil, syscall.OPEN_EXISTING, syscall.FILE_FLAG_BACKUP_SEMANTICS, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer syscall.CloseHandle(h)
	var flag uint32 = 1
	setter := kernel.NewProc("SetFileInformationByHandle")
	ok, _, callErr := setter.Call(uintptr(h), 23, uintptr(unsafe.Pointer(&flag)), unsafe.Sizeof(flag))
	if ok == 0 {
		t.Skipf("isolated directory case-sensitive flag unavailable without elevation: %v", callErr)
	}
	defer func() {
		flag = 0
		ok, _, err := setter.Call(uintptr(h), 23, uintptr(unsafe.Pointer(&flag)), unsafe.Sizeof(flag))
		if ok == 0 {
			t.Errorf("restore fixture case flag: %v", err)
		}
	}()
	if _, err := InspectWindows(dir, false); err != ErrUnverified {
		t.Fatal("case-sensitive directory accepted")
	}
	if _, err := InspectWindows(filepath.Join(dir, "new.txt"), true); err != ErrUnverified {
		t.Fatal("case-sensitive new leaf accepted")
	}
}

func TestWindowsResourceErrorsAndZeroSnapshot(t *testing.T) {
	for _, path := range []string{"", "relative", `C:relative`, `\\server\share\file`, `C:\a\..\b`, `C:\a:stream`} {
		if s, err := InspectWindows(path, true); s != nil || err != ErrUnverified || strings.Contains(err.Error(), path) && path != "" {
			t.Fatal("unsafe or revealing error")
		}
	}
	var absent *Snapshot
	for _, s := range []*Snapshot{absent, {}} {
		if s.Revalidate() != ErrUnverified || s.Exists() || s.IsDirectory() || s.Path() != "" {
			t.Fatal("empty observation accepted")
		}
	}
}
