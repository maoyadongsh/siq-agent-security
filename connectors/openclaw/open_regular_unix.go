//go:build unix

package main

import (
	"os"
	"syscall"
)

// openRegular mirrors directory/admission ADR-013: refuse final-path symlinks
// (DEV10 / M-E6) and avoid blocking on FIFOs.
func openRegular(path string) (*os.File, error) {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(fd), path), nil
}
