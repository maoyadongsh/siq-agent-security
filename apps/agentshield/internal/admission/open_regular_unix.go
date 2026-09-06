//go:build unix

package admission

import (
	"os"
	"syscall"
)

// openRegular opens path for reading without following a final symlink and
// without blocking forever on FIFO/device open. Callers must still Stat the fd
// and require a regular file that matches the pre-open FileInfo (ADR-013).
func openRegular(path string) (*os.File, error) {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC|syscall.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(fd), path), nil
}
