package privatefs

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"unsafe"
)

var (
	advapi           = syscall.NewLazyDLL("advapi32.dll")
	getSecurityInfo  = advapi.NewProc("GetSecurityInfo")
	validDescriptor  = advapi.NewProc("IsValidSecurityDescriptor")
	validACL         = advapi.NewProc("IsValidAcl")
	validSID         = advapi.NewProc("IsValidSid")
	getACLinform     = advapi.NewProc("GetAclInformation")
	getACE           = advapi.NewProc("GetAce")
	sddlToDescriptor = advapi.NewProc("ConvertStringSecurityDescriptorToSecurityDescriptorW")
)

func currentSID() (string, error) {
	token, err := syscall.OpenCurrentProcessToken()
	if err != nil {
		return "", ErrPrivate
	}
	defer token.Close()
	user, err := token.GetTokenUser()
	if err != nil {
		return "", ErrPrivate
	}
	sid, err := user.User.Sid.String()
	if err != nil {
		return "", ErrPrivate
	}
	return sid, nil
}

func nativePath(path string) (string, error) {
	// Check caller spelling before Abs/Clean can erase an ambiguous component.
	for _, part := range strings.FieldsFunc(path[len(filepath.VolumeName(path)):], func(r rune) bool { return r == '/' || r == '\\' }) {
		if part == "." || part == ".." {
			continue
		}
		if !filepath.IsLocal(part) || strings.Contains(part, ":") || strings.HasSuffix(part, ".") || strings.HasSuffix(part, " ") {
			return "", ErrPrivate
		}
	}
	abs, err := filepath.Abs(path)
	if err != nil || len(filepath.VolumeName(abs)) != 2 || strings.HasPrefix(abs, `\\`) {
		return "", ErrPrivate
	}
	return `\\?\` + abs, nil
}

func privateError(err error) error {
	if errors.Is(err, syscall.ERROR_FILE_NOT_FOUND) || errors.Is(err, syscall.ERROR_PATH_NOT_FOUND) {
		return os.ErrNotExist
	}
	if errors.Is(err, syscall.ERROR_FILE_EXISTS) || errors.Is(err, syscall.ERROR_ALREADY_EXISTS) {
		return os.ErrExist
	}
	return ErrPrivate
}

// Only object shape is checked for ambient ancestors. Their DACLs are neither
// changed nor required to be private (a private child may have a public parent).
func checkParents(path string) error {
	for dir := filepath.Dir(path); ; dir = filepath.Dir(dir) {
		native, err := nativePath(dir)
		if err != nil {
			return err
		}
		name, err := syscall.UTF16PtrFromString(native)
		if err != nil {
			return ErrPrivate
		}
		attrs, err := syscall.GetFileAttributes(name)
		if err != nil {
			return privateError(err)
		}
		if attrs&syscall.FILE_ATTRIBUTE_DIRECTORY == 0 || attrs&syscall.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
			return ErrPrivate
		}
		if dir == filepath.Dir(dir) {
			return nil
		}
	}
}

func openHandle(path string, directory bool) (*os.File, error) {
	if _, err := nativePath(path); err != nil {
		return nil, err
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return nil, ErrPrivate
	}
	native, err := nativePath(abs)
	if err != nil {
		return nil, err
	}
	if err := checkParents(abs); err != nil {
		return nil, err
	}
	name, err := syscall.UTF16PtrFromString(native)
	if err != nil {
		return nil, ErrPrivate
	}
	access, flags := uint32(syscall.GENERIC_READ), uint32(syscall.FILE_FLAG_OPEN_REPARSE_POINT)
	if directory {
		access = 0x20000 | 0x80
		flags |= syscall.FILE_FLAG_BACKUP_SEMANTICS
	}
	h, err := syscall.CreateFile(name, access, syscall.FILE_SHARE_READ|syscall.FILE_SHARE_WRITE|syscall.FILE_SHARE_DELETE, nil, syscall.OPEN_EXISTING, flags, 0)
	if err != nil {
		return nil, privateError(err)
	}
	f := os.NewFile(uintptr(h), path)
	if err := checkFile(f, directory); err != nil {
		_ = f.Close()
		return nil, err
	}
	return f, nil
}

func Open(path string) (*os.File, error) { return openHandle(path, false) }
func CheckDir(path string) error {
	f, err := openHandle(path, true)
	if err != nil {
		return err
	}
	return f.Close()
}

func checkFile(f *os.File, directory bool) error {
	if f == nil {
		return ErrPrivate
	}
	h := syscall.Handle(f.Fd())
	var info syscall.ByHandleFileInformation
	if syscall.GetFileInformationByHandle(h, &info) != nil || info.FileAttributes&syscall.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
		return ErrPrivate
	}
	if (info.FileAttributes&syscall.FILE_ATTRIBUTE_DIRECTORY != 0) != directory || (!directory && info.NumberOfLinks != 1) {
		return ErrPrivate
	}
	wantOwner, err := currentSID()
	if err != nil {
		return err
	}
	var owner *syscall.SID
	var acl, descriptor unsafe.Pointer
	r, _, _ := getSecurityInfo.Call(uintptr(h), 1, 1|4, uintptr(unsafe.Pointer(&owner)), 0, uintptr(unsafe.Pointer(&acl)), 0, uintptr(unsafe.Pointer(&descriptor)))
	if r != 0 || descriptor == nil {
		return ErrPrivate
	}
	defer syscall.LocalFree(syscall.Handle(uintptr(descriptor)))
	if ok, _, _ := validDescriptor.Call(uintptr(descriptor)); ok == 0 {
		return ErrPrivate
	}
	if owner == nil || acl == nil {
		return ErrPrivate
	}
	if ok, _, _ := validSID.Call(uintptr(unsafe.Pointer(owner))); ok == 0 {
		return ErrPrivate
	}
	ownerText, err := owner.String()
	if err != nil || ownerText != wantOwner {
		return ErrPrivate
	}
	if ok, _, _ := validACL.Call(uintptr(acl)); ok == 0 {
		return ErrPrivate
	}
	var size struct{ Count, InUse, Free uint32 }
	if ok, _, _ := getACLinform.Call(uintptr(acl), uintptr(unsafe.Pointer(&size)), unsafe.Sizeof(size), 2); ok == 0 || size.Count == 0 || size.Count > 4096 || size.InUse > 65535 {
		return ErrPrivate
	}
	for i := uint32(0); i < size.Count; i++ {
		var ace unsafe.Pointer
		if ok, _, _ := getACE.Call(uintptr(acl), uintptr(i), uintptr(unsafe.Pointer(&ace))); ok == 0 || ace == nil {
			return ErrPrivate
		}
		header := (*struct {
			Type, Flags uint8
			Size        uint16
		})(ace)
		// Only ordinary ACCESS_ALLOWED/ACCESS_DENIED entries are understood.
		if header.Type > 1 || header.Flags&^uint8(0x1f) != 0 || header.Size < 16 {
			return ErrPrivate
		}
		sidPtr := unsafe.Add(ace, 8)
		sidHead := (*[8]byte)(sidPtr)
		if sidHead[0] != 1 || sidHead[1] > 15 || 16+uint16(sidHead[1])*4 > header.Size {
			return ErrPrivate
		}
		if ok, _, _ := validSID.Call(uintptr(sidPtr)); ok == 0 {
			return ErrPrivate
		}
		sid, err := (*syscall.SID)(sidPtr).String()
		if err != nil {
			return ErrPrivate
		}
		if header.Type == 0 && sid != wantOwner && sid != "S-1-5-18" && sid != "S-1-5-32-544" {
			return ErrPrivate
		}
	}
	return nil
}

func withDescriptor(sddl string, run func(*syscall.SecurityAttributes) error) error {
	text, err := syscall.UTF16PtrFromString(sddl)
	if err != nil {
		return ErrPrivate
	}
	var descriptor unsafe.Pointer
	if ok, _, _ := sddlToDescriptor.Call(uintptr(unsafe.Pointer(text)), 1, uintptr(unsafe.Pointer(&descriptor)), 0); ok == 0 || descriptor == nil {
		return ErrPrivate
	}
	defer syscall.LocalFree(syscall.Handle(uintptr(descriptor)))
	sa := syscall.SecurityAttributes{Length: uint32(unsafe.Sizeof(syscall.SecurityAttributes{})), SecurityDescriptor: uintptr(descriptor)}
	return run(&sa)
}

func privateSDDL() (string, error) {
	user, err := currentSID()
	if err != nil {
		return "", err
	}
	return "O:" + user + "D:P(A;OICI;FA;;;" + user + ")(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", nil
}

func MkdirAll(path string) error {
	if _, err := nativePath(path); err != nil {
		return err
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return ErrPrivate
	}
	if _, err := nativePath(abs); err != nil {
		return err
	}
	if _, err := os.Lstat(abs); err == nil {
		return CheckDir(abs)
	} else if !errors.Is(err, os.ErrNotExist) {
		return privateError(err)
	}
	parent := filepath.Dir(abs)
	if parent == abs {
		return ErrPrivate
	}
	if _, err := os.Lstat(parent); errors.Is(err, os.ErrNotExist) {
		if err := MkdirAll(parent); err != nil {
			return err
		}
	} else if err != nil {
		return privateError(err)
	}
	if err := checkParents(abs); err != nil {
		return err
	}
	native, _ := nativePath(abs)
	name, err := syscall.UTF16PtrFromString(native)
	if err != nil {
		return ErrPrivate
	}
	sddl, err := privateSDDL()
	if err != nil {
		return err
	}
	err = withDescriptor(sddl, func(sa *syscall.SecurityAttributes) error { return syscall.CreateDirectory(name, sa) })
	if err != nil && !errors.Is(privateError(err), os.ErrExist) {
		return privateError(err)
	}
	return CheckDir(abs)
}

func CreateNew(path string) (*os.File, error) {
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
	sddl, err := privateSDDL()
	if err != nil {
		return nil, err
	}
	var h syscall.Handle
	err = withDescriptor(sddl, func(sa *syscall.SecurityAttributes) error {
		var e error
		h, e = syscall.CreateFile(name, syscall.GENERIC_READ|syscall.GENERIC_WRITE, syscall.FILE_SHARE_READ, sa, syscall.CREATE_NEW, syscall.FILE_ATTRIBUTE_NORMAL|syscall.FILE_FLAG_OPEN_REPARSE_POINT, 0)
		return e
	})
	if err != nil {
		return nil, privateError(err)
	}
	f := os.NewFile(uintptr(h), path)
	if err := CheckFile(f); err != nil {
		_ = f.Close()
		return nil, err
	}
	return f, nil
}

func CreateTemp(dir, pattern string) (*os.File, error) {
	if strings.ContainsAny(pattern, `/\:`) {
		return nil, ErrPrivate
	}
	for i := 0; i < 16; i++ {
		var random [16]byte
		if _, err := rand.Read(random[:]); err != nil {
			return nil, err
		}
		part := hex.EncodeToString(random[:])
		name := pattern + part
		if at := strings.LastIndex(pattern, "*"); at >= 0 {
			name = pattern[:at] + part + pattern[at+1:]
		}
		f, err := CreateNew(filepath.Join(dir, name))
		if errors.Is(err, os.ErrExist) {
			continue
		}
		return f, err
	}
	return nil, ErrPrivate
}
