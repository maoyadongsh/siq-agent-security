package state

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

var setWriterFileInformation = syscall.NewLazyDLL("kernel32.dll").NewProc("SetFileInformationByHandle")

func processAlive(pid int) bool {
	return windowsProcessAlive(pid, syscall.OpenProcess, syscall.WaitForSingleObject, syscall.CloseHandle)
}

func windowsProcessAlive(pid int, open func(uint32, bool, uint32) (syscall.Handle, error), wait func(syscall.Handle, uint32) (uint32, error), closeHandle func(syscall.Handle) error) bool {
	// Do not wrap an invalid PID into the identity of a different process.
	if pid <= 0 || uint64(pid) > uint64(^uint32(0)) {
		return true
	}
	h, err := open(syscall.SYNCHRONIZE, false, uint32(pid))
	if err != nil {
		return !errors.Is(err, syscall.Errno(87)) // ERROR_INVALID_PARAMETER: nonzero PID does not exist.
	}
	defer closeHandle(h)
	result, err := wait(h, 0)
	return err != nil || result != syscall.WAIT_OBJECT_0
}

func quarantineStaleLock(path string) error {
	return quarantineWindowsLock(path, processAlive)
}

func quarantineWindowsLock(path string, alive func(int) bool) error {
	nativePath, err := windowsWriterPath(path)
	if err != nil {
		return err
	}
	name, err := syscall.UTF16PtrFromString(nativePath)
	if err != nil {
		return errors.New("state: invalid writer lock path")
	}
	// No sharing: nobody can replace, rename, truncate or open this object for
	// a second reclamation while its contents and process identity are checked.
	const deleteAccess = 0x00010000
	h, err := syscall.CreateFile(name, syscall.GENERIC_READ|deleteAccess, 0, nil, syscall.OPEN_EXISTING, syscall.FILE_FLAG_OPEN_REPARSE_POINT, 0)
	if err != nil {
		return ErrWriterBusy
	}
	f := os.NewFile(uintptr(h), path)
	defer f.Close()
	var info syscall.ByHandleFileInformation
	if err := syscall.GetFileInformationByHandle(h, &info); err != nil || info.NumberOfLinks != 1 || info.FileAttributes&(syscall.FILE_ATTRIBUTE_REPARSE_POINT|syscall.FILE_ATTRIBUTE_DIRECTORY) != 0 {
		return errors.New("state: unsafe writer lock")
	}
	raw, err := io.ReadAll(io.LimitReader(f, 4097))
	if err != nil || len(raw) > 4096 {
		return errors.New("state: serve.lock unreadable")
	}
	pid, _, err := parseLockFile(raw)
	if err != nil {
		return errors.New("state: invalid writer lock")
	}
	if alive(pid) {
		return ErrWriterBusy
	}
	owner, err := randomOwner()
	if err != nil {
		return err
	}
	stale, err := filepath.Abs(path + ".stale." + owner)
	if err != nil {
		return errors.New("state: invalid stale lock path")
	}
	return renameWriterHandle(h, stale)
}

func renameWriterHandle(h syscall.Handle, target string) error {
	nativePath, err := windowsWriterPath(target)
	if err != nil {
		return err
	}
	name, err := syscall.UTF16FromString(nativePath)
	if err != nil || len(name) > 32768 {
		return errors.New("state: invalid stale lock path")
	}
	// FILE_RENAME_INFO uses native pointer alignment on both 32 and 64 bit.
	// ReplaceIfExists stays zero: never overwrite a prior quarantine object.
	info := new(struct {
		ReplaceIfExists uint32
		RootDirectory   syscall.Handle
		FileNameLength  uint32
		FileName        [32768]uint16
	})
	info.FileNameLength = uint32((len(name) - 1) * 2)
	copy(info.FileName[:], name)
	size := unsafe.Offsetof(info.FileName) + uintptr(info.FileNameLength)
	ok, _, _ := setWriterFileInformation.Call(uintptr(h), 3, uintptr(unsafe.Pointer(info)), size) // FileRenameInfo
	if ok == 0 {
		return errors.New("state: cannot quarantine stale serve.lock")
	}
	return nil
}

// The public root has already passed stateformat validation. The extended form
// is only an internal OS spelling, allowing recovery at the same long paths
// that os.OpenFile accepts when creating a Writer.
func windowsWriterPath(path string) (string, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", errors.New("state: invalid writer lock path")
	}
	if strings.HasPrefix(abs, `\\`) {
		return `\\?\UNC\` + strings.TrimPrefix(abs, `\\`), nil
	}
	return `\\?\` + abs, nil
}
