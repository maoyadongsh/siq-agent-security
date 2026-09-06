package state

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// LockFile is the single-writer marker under the state directory (dev-spec §2.3).
const LockFile = "serve.lock"

// ErrWriterBusy means another live process holds the write lock.
var ErrWriterBusy = errors.New("state: write lock held by another process")

// Writer is exclusive ownership of local state mutations for one process.
type Writer struct {
	Dir   string
	path  string
	owner string
	pid   int
}

// AcquireWriter creates serve.lock with O_EXCL. A lock whose pid is proven
// dead is renamed aside (never silently deleted) and acquisition is retried.
func AcquireWriter(dir string) (*Writer, error) {
	if dir == "" {
		return nil, errors.New("state: directory required")
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	path := filepath.Join(dir, LockFile)
	owner, err := randomOwner()
	if err != nil {
		return nil, err
	}
	for attempt := 0; attempt < 2; attempt++ {
		f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
		if err == nil {
			pid := os.Getpid()
			if _, err := fmt.Fprintf(f, "%d\n%s\n%s\n", pid, owner, time.Now().UTC().Format(time.RFC3339Nano)); err != nil {
				_ = f.Close()
				_ = os.Remove(path)
				return nil, err
			}
			if err := f.Close(); err != nil {
				_ = os.Remove(path)
				return nil, err
			}
			return &Writer{Dir: dir, path: path, owner: owner, pid: pid}, nil
		}
		if !errors.Is(err, os.ErrExist) {
			return nil, err
		}
		heldPID, _, readErr := readLockFile(path)
		if readErr != nil {
			return nil, fmt.Errorf("state: serve.lock unreadable: %w", readErr)
		}
		if processAlive(heldPID) {
			return nil, fmt.Errorf("%w (pid %d); submit writes through serve HTTP or wait", ErrWriterBusy, heldPID)
		}
		stale := fmt.Sprintf("%s.stale.%d", path, time.Now().UnixNano())
		if err := os.Rename(path, stale); err != nil {
			return nil, fmt.Errorf("state: cannot quarantine stale serve.lock: %w", err)
		}
	}
	return nil, ErrWriterBusy
}

// Release removes the lock only if this writer still owns it.
func (w *Writer) Release() error {
	if w == nil || w.path == "" {
		return nil
	}
	pid, owner, err := readLockFile(w.path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return err
	}
	if pid != w.pid || (w.owner != "" && owner != "" && owner != w.owner) {
		return errors.New("state: refuse to release serve.lock owned by another writer")
	}
	return os.Remove(w.path)
}

// WriterHeld reports whether a live process currently owns serve.lock.
func WriterHeld(dir string) (bool, int, error) {
	path := filepath.Join(dir, LockFile)
	pid, _, err := readLockFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return false, 0, nil
	}
	if err != nil {
		return false, 0, err
	}
	if !processAlive(pid) {
		return false, pid, nil
	}
	return true, pid, nil
}

func readLockFile(path string) (pid int, owner string, err error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return 0, "", err
	}
	lines := strings.Split(string(raw), "\n")
	if len(lines) == 0 || strings.TrimSpace(lines[0]) == "" {
		return 0, "", errors.New("empty lock")
	}
	pid, err = strconv.Atoi(strings.TrimSpace(lines[0]))
	if err != nil || pid <= 0 {
		return 0, "", errors.New("invalid lock pid")
	}
	if len(lines) > 1 {
		owner = strings.TrimSpace(lines[1])
	}
	return pid, owner, nil
}

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
	if runtime.GOOS == "windows" {
		// Stdlib cannot prove death without Win32 APIs; stay conservative.
		return true
	}
	cmd := exec.Command("kill", "-0", strconv.Itoa(pid))
	return cmd.Run() == nil
}

func randomOwner() (string, error) {
	var b [8]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(b[:]), nil
}
