package privatefs

import (
	"errors"
	"os"
	"path/filepath"
	"syscall"
	"unsafe"
)

// PublishNew moves the same private single-link object without replacing a
// target. A true moved result remains true even if closing the handle fails.
func PublishNew(source, target string, created os.FileInfo) (moved bool, resultErr error) {
	if created == nil {
		return false, ErrPrivate
	}
	if err := CheckDir(filepath.Dir(source)); err != nil {
		return false, err
	}
	if err := CheckDir(filepath.Dir(target)); err != nil {
		return false, err
	}
	native, err := nativePath(source)
	if err != nil {
		return false, err
	}
	name, err := syscall.UTF16PtrFromString(native)
	if err != nil {
		return false, ErrPrivate
	}
	const deleteAccess = 0x10000
	h, err := syscall.CreateFile(name, syscall.GENERIC_READ|deleteAccess, 0, nil, syscall.OPEN_EXISTING, syscall.FILE_FLAG_OPEN_REPARSE_POINT, 0)
	if err != nil {
		return false, privateError(err)
	}
	f := os.NewFile(uintptr(h), source)
	defer func() { resultErr = errors.Join(resultErr, f.Close()) }()
	actual, err := f.Stat()
	if err != nil || !actual.Mode().IsRegular() || !os.SameFile(created, actual) || CheckFile(f) != nil {
		return false, ErrPrivate
	}
	destination, err := nativePath(target)
	if err != nil {
		return false, err
	}
	units, err := syscall.UTF16FromString(destination)
	if err != nil || len(units) > 32768 {
		return false, ErrPrivate
	}
	info := new(struct {
		ReplaceIfExists uint32
		RootDirectory   syscall.Handle
		FileNameLength  uint32
		FileName        [32768]uint16
	})
	// ReplaceIfExists remains zero, including on collision and retries.
	info.FileNameLength = uint32((len(units) - 1) * 2)
	copy(info.FileName[:], units)
	set := syscall.NewLazyDLL("kernel32.dll").NewProc("SetFileInformationByHandle")
	ok, _, err := set.Call(uintptr(h), 3, uintptr(unsafe.Pointer(info)), unsafe.Offsetof(info.FileName)+uintptr(info.FileNameLength))
	if ok == 0 {
		return false, privateError(err)
	}
	return true, nil
}
