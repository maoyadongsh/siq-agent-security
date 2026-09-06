//go:build unix

package main

import (
	"os"
	"syscall"
)

// openRegular mirrors admission ADR-013 / DEV10-H: refuse final-path symlinks
// and avoid FIFO hang on Unix.
func openRegular(path string) (*os.File, error) {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(fd), path), nil
}
