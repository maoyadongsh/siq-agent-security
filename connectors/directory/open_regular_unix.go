//go:build unix

package main

import (
	"os"
	"syscall"
)

// openRegular mirrors admission ADR-013: no final symlink follow, no FIFO hang.
func openRegular(path string) (*os.File, error) {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(fd), path), nil
}
