//go:build !windows

package state

import (
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"time"
)

func processAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	if pid == os.Getpid() {
		return true
	}
	if _, err := os.Stat(fmt.Sprintf("/proc/%d", pid)); err == nil {
		return true
	}
	return exec.Command("kill", "-0", strconv.Itoa(pid)).Run() == nil
}

func quarantineStaleLock(path string) error {
	pid, _, err := readLockFile(path)
	if err != nil {
		return fmt.Errorf("state: serve.lock unreadable: %w", err)
	}
	if processAlive(pid) {
		return ErrWriterBusy
	}
	stale := fmt.Sprintf("%s.stale.%d", path, time.Now().UnixNano())
	if err := os.Rename(path, stale); err != nil {
		return fmt.Errorf("state: cannot quarantine stale serve.lock: %w", err)
	}
	return nil
}
