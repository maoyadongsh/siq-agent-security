// Package linktest creates links only in isolated test fixtures.
// Product code must not import this package.
package linktest

import (
	"errors"
	"os"
	"runtime"
	"syscall"
	"testing"
)

// Symlink skips only the precise Windows privilege failure. Call it in a
// narrow subtest so unavailable leaf links do not hide unrelated assertions.
func Symlink(t *testing.T, target, link string) {
	t.Helper()
	if err := os.Symlink(target, link); err != nil {
		if runtime.GOOS == "windows" && errors.Is(err, syscall.Errno(1314)) {
			t.Skip("leaf symlink unavailable: Windows ERROR_PRIVILEGE_NOT_HELD; this assertion is unverified")
		}
		t.Fatal(err)
	}
}
