package privatefs

import (
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

// FileSecurity records the owner and DACL of a pinned private object. SDDL is
// recovery material, never public diagnostics. It includes deny/inheritance ACEs.
func (s *ReadSnapshot) FileSecurity(name string) (string, error) {
	f, err := s.openFile(name)
	if err != nil {
		return "", err
	}
	if err := checkFile(f, false); err != nil {
		return "", err
	}
	return fileSecurity(f)
}

func fileSecurity(f *os.File) (string, error) {
	var descriptor unsafe.Pointer
	r, _, _ := getSecurityInfo.Call(f.Fd(), 1, 1|4, 0, 0, 0, 0, uintptr(unsafe.Pointer(&descriptor)))
	if r != 0 || descriptor == nil {
		return "", ErrPrivate
	}
	defer syscall.LocalFree(syscall.Handle(uintptr(descriptor)))
	var text *uint16
	var size uint32
	convert := advapi.NewProc("ConvertSecurityDescriptorToStringSecurityDescriptorW")
	if ok, _, _ := convert.Call(uintptr(descriptor), 1, 1|4, uintptr(unsafe.Pointer(&text)), uintptr(unsafe.Pointer(&size))); ok == 0 || text == nil {
		return "", ErrPrivate
	}
	defer syscall.LocalFree(syscall.Handle(uintptr(unsafe.Pointer(text))))
	if size < 2 || size > 65536 {
		return "", ErrPrivate
	}
	return syscall.UTF16ToString(unsafe.Slice(text, int(size))), nil
}

// CreateNewWithSecurity preserves a reviewed descriptor at creation only. It
// never opens or changes an existing object, and refuses unsafe descriptors
// before the caller can write any bytes. The caller owns the new scratch name.
func CreateNewWithSecurity(path, security string) (*os.File, error) {
	if security == "" || len(security) > 65536 {
		return nil, ErrPrivate
	}
	if err := CheckDir(filepath.Dir(path)); err != nil {
		return nil, err
	}
	native, err := nativePath(path)
	if err != nil {
		return nil, err
	}
	name, err := syscall.UTF16PtrFromString(native)
	if err != nil {
		return nil, ErrPrivate
	}
	var h syscall.Handle
	err = withDescriptor(security, func(sa *syscall.SecurityAttributes) error {
		var e error
		h, e = syscall.CreateFile(name, syscall.GENERIC_READ|syscall.GENERIC_WRITE, syscall.FILE_SHARE_READ, sa, syscall.CREATE_NEW, syscall.FILE_ATTRIBUTE_NORMAL|syscall.FILE_FLAG_OPEN_REPARSE_POINT, 0)
		return e
	})
	if err != nil {
		return nil, privateError(err)
	}
	f := os.NewFile(uintptr(h), path)
	if err := checkFile(f, false); err != nil {
		_ = f.Close()
		return nil, err
	}
	actual, err := fileSecurity(f)
	if err != nil || !EquivalentSecurity(actual, security) {
		_ = f.Close()
		return nil, ErrPrivate
	}
	return f, nil
}

// EquivalentSecurity ignores only the provider's AUTO_INHERITED bookkeeping
// bit, which CREATE_NEW clears even while retaining all inherited ACE flags.
// It does not reorder ACEs or ignore deny, owner, protection or inheritance.
func EquivalentSecurity(a, b string) bool {
	normalize := func(value string) string {
		at := strings.Index(value, "D:")
		if at < 0 {
			return value
		}
		end := strings.Index(value[at+2:], "(")
		if end < 0 {
			end = len(value)
		} else {
			end += at + 2
		}
		return value[:at+2] + strings.ReplaceAll(value[at+2:end], "AI", "") + value[end:]
	}
	return normalize(a) == normalize(b)
}
