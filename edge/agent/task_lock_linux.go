//go:build linux

package main

import (
	"errors"
	"os"
	"path/filepath"
	"syscall"
)

// Kernel-owned lock survives stale lock files, but never process exit.
// The lock inode is deliberately retained; unlinking would split ownership.
func acquireTaskLock() (func(), error) {
	dir, err := StateDir()
	if err != nil {
		return nil, err
	}
	info, err := os.Lstat(dir)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 {
		return nil, errors.New("unsafe edge state directory")
	}
	fd, err := syscall.Open(filepath.Join(dir, "tasks.lock"), syscall.O_CREAT|syscall.O_RDWR|syscall.O_CLOEXEC|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0600)
	if err != nil {
		return nil, errors.New("edge task lock unavailable")
	}
	f := os.NewFile(uintptr(fd), "edge-task-lock")
	var st syscall.Stat_t
	if syscall.Fstat(fd, &st) != nil || st.Mode&syscall.S_IFMT != syscall.S_IFREG || st.Mode&0077 != 0 || st.Uid != uint32(os.Geteuid()) || st.Nlink != 1 {
		f.Close()
		return nil, errors.New("unsafe edge task lock")
	}
	if syscall.Flock(fd, syscall.LOCK_EX|syscall.LOCK_NB) != nil {
		f.Close()
		return nil, errors.New("edge task runner already active")
	}
	return func() { _ = syscall.Flock(fd, syscall.LOCK_UN); _ = f.Close() }, nil
}
