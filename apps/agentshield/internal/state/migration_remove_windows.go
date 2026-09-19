package state

import (
	"errors"
	"os"
	"syscall"
	"unsafe"
)

func migrationRemoveScratch(path string, created os.FileInfo) (resultErr error) {
	native, err := windowsWriterPath(path)
	if err != nil {
		return err
	}
	name, err := syscall.UTF16PtrFromString(native)
	if err != nil {
		return errors.New("state-migrate: invalid scratch path")
	}
	const deleteAndReadAttributes = 0x10000 | 0x80
	h, err := syscall.CreateFile(name, deleteAndReadAttributes, syscall.FILE_SHARE_READ|syscall.FILE_SHARE_WRITE|syscall.FILE_SHARE_DELETE, nil, syscall.OPEN_EXISTING, syscall.FILE_FLAG_OPEN_REPARSE_POINT, 0)
	if err != nil {
		return errors.New("state-migrate: cannot open owned scratch for cleanup")
	}
	f := os.NewFile(uintptr(h), path)
	defer func() { resultErr = errors.Join(resultErr, f.Close()) }()
	actual, err := f.Stat()
	if err != nil || !actual.Mode().IsRegular() || !os.SameFile(created, actual) {
		return errors.New("state-migrate: scratch identity changed")
	}
	// FileDispositionInfoEx, DELETE | IGNORE_READONLY_ATTRIBUTE. Unlike
	// os.Remove's Windows fallback, this leaves every other hard link's
	// read-only attribute intact. Unsupported systems fail without fallback.
	flags := uint32(0x11)
	ok, _, _ := setWriterFileInformation.Call(uintptr(h), 21, uintptr(unsafe.Pointer(&flags)), unsafe.Sizeof(flags))
	if ok == 0 {
		return errors.New("state-migrate: cannot remove owned scratch without changing attributes")
	}
	return nil
}
