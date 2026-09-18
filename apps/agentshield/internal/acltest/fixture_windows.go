// Package acltest is used only by Windows tests with synthetic temporary state.
package acltest

import (
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"unsafe"
)

// BroadenRead adds Everyone read access to one known fixture. The returned
// function restores a private fixture DACL; production never imports this package.
func BroadenRead(t *testing.T, root, path string) func() {
	t.Helper()
	rel, err := filepath.Rel(root, path)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) || !filepath.IsAbs(root) {
		t.Fatal("ACL fixture outside isolated root")
	}
	token, err := syscall.OpenCurrentProcessToken()
	if err != nil {
		t.Fatal(err)
	}
	defer token.Close()
	user, err := token.GetTokenUser()
	if err != nil {
		t.Fatal(err)
	}
	sid, err := user.User.Sid.String()
	if err != nil {
		t.Fatal(err)
	}
	dll := syscall.NewLazyDLL("advapi32.dll")
	convert := dll.NewProc("ConvertStringSecurityDescriptorToSecurityDescriptorW")
	set := dll.NewProc("SetFileSecurityW")
	name, err := syscall.UTF16PtrFromString(`\\?\` + path)
	if err != nil {
		t.Fatal(err)
	}
	apply := func(extra string) {
		t.Helper()
		text, err := syscall.UTF16PtrFromString("D:P(A;OICI;FA;;;" + sid + ")(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)" + extra)
		if err != nil {
			t.Fatal(err)
		}
		var descriptor unsafe.Pointer
		if ok, _, e := convert.Call(uintptr(unsafe.Pointer(text)), 1, uintptr(unsafe.Pointer(&descriptor)), 0); ok == 0 {
			t.Fatal(e)
		}
		defer syscall.LocalFree(syscall.Handle(uintptr(descriptor)))
		if ok, _, e := set.Call(uintptr(unsafe.Pointer(name)), 4|0x80000000, uintptr(descriptor)); ok == 0 {
			t.Fatal(e)
		}
	}
	apply("(A;;GR;;;WD)")
	restore := func() { apply("") }
	t.Cleanup(restore)
	return restore
}
