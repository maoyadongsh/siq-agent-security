//go:build linux

package main

import (
	"errors"
	"os"
	"syscall"
)

// Ordinary task and state mutation commands must not consume mixed upgrade state.
func acquireTaskLock() (func(), error) {
	release, err := acquireRawTaskLock()
	if err != nil {
		return nil, err
	}
	if err := requireNoUpgradePending(); err != nil {
		release()
		return nil, err
	}
	return release, nil
}

// Internal recovery lock, never exposed as a CLI bypass. The kernel-owned lock
// survives stale files but not process exit. Retain its inode to avoid split owners.
func acquireRawTaskLock() (func(), error) {
	dir, err := scheduleStateDirectory()
	if err != nil {
		return nil, errors.New("unsafe edge state directory")
	}
	defer dir.Close()
	fd, err := syscall.Openat(int(dir.Fd()), "tasks.lock", syscall.O_CREAT|syscall.O_RDWR|syscall.O_CLOEXEC|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0600)
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
