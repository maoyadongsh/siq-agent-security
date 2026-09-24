//go:build unix

package main

import (
	"fmt"
	"os"
	"syscall"
)

func openRegular(path string) (*os.File, error) {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(fd), path), nil
}

func validatePrivateOwner(info os.FileInfo) error {
	statInfo, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return fmt.Errorf("owner metadata unavailable")
	}
	if statInfo.Uid != uint32(os.Geteuid()) {
		return fmt.Errorf("owner mismatch")
	}
	if info.Mode().Perm()&0o077 != 0 {
		return fmt.Errorf("group or other permissions present")
	}
	return nil
}

func validateSingleLink(info os.FileInfo) error {
	statInfo, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return fmt.Errorf("link metadata unavailable")
	}
	if statInfo.Nlink != 1 {
		return fmt.Errorf("hard-linked file refused")
	}
	return nil
}
