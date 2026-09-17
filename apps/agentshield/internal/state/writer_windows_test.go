package state

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"
)

func TestWindowsProcessProbeFailsClosed(t *testing.T) {
	for _, tc := range []struct {
		name       string
		openErr    error
		waitResult uint32
		waitErr    error
		alive      bool
	}{
		{"absent", syscall.Errno(87), 0, nil, false},
		{"denied", syscall.ERROR_ACCESS_DENIED, 0, nil, true},
		{"unknown-open-error", syscall.Errno(123), 0, nil, true},
		{"running", nil, syscall.WAIT_TIMEOUT, nil, true},
		{"exited", nil, syscall.WAIT_OBJECT_0, nil, false},
		{"wait-error", nil, syscall.WAIT_OBJECT_0, syscall.ERROR_ACCESS_DENIED, true},
		{"wait-failed", nil, 0xffffffff, nil, true},
		{"unexpected-wait", nil, 123, nil, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			closed, waited := 0, 0
			got := windowsProcessAlive(1234, func(access uint32, inherit bool, pid uint32) (syscall.Handle, error) {
				if access != syscall.SYNCHRONIZE || inherit || pid != 1234 {
					t.Fatal("unsafe process open")
				}
				return 17, tc.openErr
			}, func(h syscall.Handle, ms uint32) (uint32, error) {
				if h != 17 || ms != 0 {
					t.Fatal("unsafe wait")
				}
				waited++
				return tc.waitResult, tc.waitErr
			}, func(h syscall.Handle) error { closed++; return nil })
			wantCalls := 0
			if tc.openErr == nil {
				wantCalls = 1
			}
			if got != tc.alive || closed != wantCalls || waited != wantCalls {
				t.Fatalf("alive=%v close=%d wait=%d", got, closed, waited)
			}
		})
	}
	invalid := []int{-1, 0}
	if strconv.IntSize == 64 {
		overflow := uint64(1)<<32 + uint64(os.Getpid())
		invalid = append(invalid, int(overflow))
	}
	for _, pid := range invalid {
		if !windowsProcessAlive(pid, func(uint32, bool, uint32) (syscall.Handle, error) {
			t.Fatal("invalid PID passed to OS")
			return 0, nil
		}, nil, nil) {
			t.Fatal("invalid PID declared dead")
		}
	}
}

func TestWindowsWriterCrashRecovery(t *testing.T) {
	if os.Getenv("SIQ_TEST_WRITER_CHILD") == "1" {
		w, err := AcquireWriter(os.Getenv("SIQ_TEST_WRITER_DIR"))
		if err != nil {
			t.Fatal(err)
		}
		defer w.Release()
		fmt.Println("writer-ready")
		time.Sleep(time.Minute)
		return
	}
	dir := t.TempDir()
	cmd := exec.Command(os.Args[0], "-test.run=^TestWindowsWriterCrashRecovery$")
	cmd.Env = append(os.Environ(), "SIQ_TEST_WRITER_CHILD=1", "SIQ_TEST_WRITER_DIR="+dir)
	out, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	waited := false
	defer func() {
		if !waited {
			_ = cmd.Process.Kill()
			_ = cmd.Wait()
		}
	}()
	ready := make(chan string, 1)
	go func() { line, _ := bufio.NewReader(out).ReadString('\n'); ready <- line }()
	select {
	case line := <-ready:
		if strings.TrimSpace(line) != "writer-ready" {
			t.Fatal("child did not acquire writer")
		}
	case <-time.After(15 * time.Second):
		t.Fatal("child startup timeout")
	}
	lockPath := filepath.Join(dir, LockFile)
	before, err := os.ReadFile(lockPath)
	if err != nil {
		t.Fatal(err)
	}
	if !processAlive(cmd.Process.Pid) {
		t.Fatal("live child declared dead")
	}
	if _, err := AcquireWriter(dir); !errors.Is(err, ErrWriterBusy) {
		t.Fatalf("live owner not protected: %v", err)
	}
	if err := cmd.Process.Kill(); err != nil {
		t.Fatal(err)
	}
	if err := cmd.Wait(); err == nil {
		t.Fatal("expected abnormal child exit")
	}
	waited = true
	if processAlive(cmd.Process.Pid) {
		t.Fatal("exited child declared alive")
	}
	w, err := AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	stale, _ := filepath.Glob(lockPath + ".stale.*")
	if len(stale) != 1 {
		t.Fatal("expected one preserved stale lock")
	}
	got, err := os.ReadFile(stale[0])
	if err != nil || !bytes.Equal(got, before) {
		t.Fatal("stale lock content lost")
	}
	if _, err := AcquireWriter(dir); !errors.Is(err, ErrWriterBusy) {
		t.Fatal("replacement writer not exclusive")
	}
}

func TestWindowsReclaimPinsObservedLock(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, LockFile)
	old := []byte("999999999\nold-owner\n")
	if err := os.WriteFile(path, old, 0600); err != nil {
		t.Fatal(err)
	}
	if err := quarantineWindowsLock(path, func(int) bool {
		// Deterministic race window: all attempts to replace the checked lock
		// must fail while the claimant's exclusive handle remains open.
		if err := os.Rename(path, path+".moved"); err == nil {
			t.Fatal("lock moved during probe")
		}
		if err := os.Remove(path); err == nil {
			t.Fatal("lock removed during probe")
		}
		if err := os.WriteFile(path, []byte("replacement"), 0600); err == nil {
			t.Fatal("lock changed during probe")
		}
		if err := quarantineWindowsLock(path, func(int) bool { t.Fatal("second claimant reached probe"); return false }); err == nil {
			t.Fatal("second reclamation succeeded")
		}
		return false
	}); err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	current, _ := os.ReadFile(path)
	if err := quarantineStaleLock(path); !errors.Is(err, ErrWriterBusy) {
		t.Fatal("live replacement quarantined")
	}
	after, _ := os.ReadFile(path)
	if !bytes.Equal(current, after) {
		t.Fatal("live replacement changed")
	}
	stale, _ := filepath.Glob(path + ".stale.*")
	if len(stale) != 1 {
		t.Fatal("unexpected stale locks")
	}
	got, _ := os.ReadFile(stale[0])
	if !bytes.Equal(old, got) {
		t.Fatal("wrong object quarantined")
	}
}

func TestWindowsConcurrentStaleAcquisition(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, LockFile), []byte("999999999\nold\n"), 0600); err != nil {
		t.Fatal(err)
	}
	start := make(chan struct{})
	winners := make(chan *Writer, 24)
	var wg sync.WaitGroup
	for i := 0; i < 24; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			if w, err := AcquireWriter(dir); err == nil {
				winners <- w
			}
		}()
	}
	close(start)
	wg.Wait()
	close(winners)
	count := 0
	for w := range winners {
		count++
		if err := w.Release(); err != nil {
			t.Fatal(err)
		}
	}
	if count != 1 {
		t.Fatalf("expected one winner, got %d", count)
	}
}

func TestWindowsReclaimRejectsUnsafeLock(t *testing.T) {
	for _, kind := range []string{"malformed", "oversize", "hardlink", "live"} {
		t.Run(kind, func(t *testing.T) {
			dir := t.TempDir()
			path := filepath.Join(dir, LockFile)
			raw := []byte("999999999\nold\n")
			if kind == "malformed" {
				raw = []byte("not-a-pid\n")
			}
			if kind == "oversize" {
				raw = append(raw, bytes.Repeat([]byte("x"), 4096)...)
			}
			if kind == "live" {
				raw = []byte(fmt.Sprintf("%d\nlive\n", os.Getpid()))
			}
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
			if kind == "hardlink" {
				if err := os.Link(path, filepath.Join(dir, "alias")); err != nil {
					t.Fatal(err)
				}
			}
			if err := quarantineStaleLock(path); err == nil {
				t.Fatal("unsafe reclaim accepted")
			}
			got, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(got, raw) {
				t.Fatal("rejected lock mutated")
			}
			stale, _ := filepath.Glob(path + ".stale.*")
			if len(stale) != 0 {
				t.Fatal("rejected lock quarantined")
			}
		})
	}
}

func TestWindowsHandleRenameRefusesExistingTarget(t *testing.T) {
	dir := t.TempDir()
	path, target := filepath.Join(dir, "source"), filepath.Join(dir, "target")
	for _, p := range []string{path, target} {
		if err := os.WriteFile(p, []byte(filepath.Base(p)), 0600); err != nil {
			t.Fatal(err)
		}
	}
	name, _ := syscall.UTF16PtrFromString(path)
	h, err := syscall.CreateFile(name, syscall.GENERIC_READ|0x10000, 0, nil, syscall.OPEN_EXISTING, 0, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer syscall.CloseHandle(h)
	if err := renameWriterHandle(h, target); err == nil {
		t.Fatal("existing target overwritten")
	}
	got, err := os.ReadFile(target)
	if err != nil || string(got) != "target" {
		t.Fatal("target changed")
	}
}

func TestWindowsWriterRecoveryLongUnicodePath(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "中文 空格", strings.Repeat("long", 30), strings.Repeat("deep", 30))
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, LockFile)
	if err := os.WriteFile(path, []byte("999999999\nold\n"), 0600); err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := w.Release(); err != nil {
		t.Fatal(err)
	}
	stale, _ := filepath.Glob(path + ".stale.*")
	if len(stale) != 1 {
		t.Fatal("long-path stale lock not preserved")
	}
}
