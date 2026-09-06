package admission

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

func TestFIFOIsRefusedWithoutOpening(t *testing.T) {
	if dir := os.Getenv("SIQ_TEST_FIFO_DIR"); dir != "" {
		if _, err := Admit(dir, testOpts(t, dir, "unknown")); err == nil {
			t.Fatal("FIFO accepted")
		}
		if _, _, err := HashDir(dir, DefaultLimits); err == nil {
			t.Fatal("FIFO received a content hash")
		}
		return
	}
	if runtime.GOOS == "windows" {
		t.Skip("POSIX FIFO behavior; Windows special-file behavior requires platform validation")
	}
	mkfifo, err := exec.LookPath("mkfifo")
	if err != nil {
		t.Skip("mkfifo required for real FIFO regression")
	}
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "SKILL.md"), []byte("Hello."), 0o600); err != nil {
		t.Fatal(err)
	}
	if out, err := exec.Command(mkfifo, filepath.Join(root, "pipe")).CombinedOutput(); err != nil {
		t.Fatalf("mkfifo: %v %s", err, out)
	}
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, exe, "-test.run=^TestFIFOIsRefusedWithoutOpening$")
	cmd.Env = append(os.Environ(), "SIQ_TEST_FIFO_DIR="+root)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("FIFO scan must return a controlled error without blocking: %v %s", err, out)
	}
}

func TestHashDirRejectsSymlinkEscape(t *testing.T) {
	root := t.TempDir()
	out := filepath.Join(t.TempDir(), "outside.txt")
	if err := os.WriteFile(out, []byte("outside"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(out, filepath.Join(root, "link")); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	if hash, _, err := HashDir(root, DefaultLimits); err == nil || hash != "" {
		t.Fatal("out-of-scope tree received a content hash")
	}
}

func TestRootSymlinkHashesTheSameTree(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "plain"), []byte("text without extension"), 0o600); err != nil {
		t.Fatal(err)
	}
	alias := filepath.Join(t.TempDir(), "alias")
	if err := os.Symlink(root, alias); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	want, _, err := HashDir(root, DefaultLimits)
	if err != nil {
		t.Fatal(err)
	}
	got, files, err := HashDir(alias, DefaultLimits)
	if err != nil || got != want || len(files) != 1 {
		t.Fatalf("root alias changed content: %v, files=%d", err, len(files))
	}
}

func TestExtensionlessBinaryDoesNotPanic(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "SKILL.md"), []byte("---\nname: test\ndescription: Test.\n---\nHello."), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "payload"), []byte{0, 1, 2}, 0o600); err != nil {
		t.Fatal(err)
	}
	res, err := Admit(root, testOpts(t, root, "unknown"))
	if err != nil {
		t.Fatal(err)
	}
	if !findingRules(res, dispInfo)["adm-binary-file"] {
		t.Fatal("non-executable binary should remain a reported informational artifact")
	}
}

func TestHashDirRefusesIncompleteManifest(t *testing.T) {
	root := t.TempDir()
	for _, name := range []string{"a.txt", "b.txt"} {
		if err := os.WriteFile(filepath.Join(root, name), []byte("abc"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	lim := DefaultLimits
	lim.MaxTotal = 6
	if _, files, err := HashDir(root, lim); err != nil || len(files) != 2 {
		t.Fatalf("exact budget must work: %v, %d files", err, len(files))
	}
	lim.MaxTotal = 5
	if hash, _, err := HashDir(root, lim); err == nil || hash != "" {
		t.Fatal("over-budget tree received a usable content hash")
	}
	lim = DefaultLimits
	lim.MaxFiles = 1
	if hash, _, err := HashDir(root, lim); err == nil || hash != "" {
		t.Fatal("partial file manifest received a usable content hash")
	}
}

func TestHashDirRequiresDirectoryRoot(t *testing.T) {
	path := filepath.Join(t.TempDir(), "SKILL.md")
	if err := os.WriteFile(path, []byte("ordinary file"), 0o600); err != nil {
		t.Fatal(err)
	}
	if hash, _, err := HashDir(path, DefaultLimits); err == nil || hash != "" {
		t.Fatal("file root received an empty-directory hash")
	}
}

func TestOpenRegularRefusesSymlink(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("O_NOFOLLOW openRegular is Unix-only; Windows residual TOCTOU is ADR-013")
	}
	dir := t.TempDir()
	target := filepath.Join(dir, "target.txt")
	if err := os.WriteFile(target, []byte("payload"), 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "link.txt")
	if err := os.Symlink(target, link); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	f, err := openRegular(link)
	if err == nil {
		f.Close()
		t.Fatal("openRegular must not follow a final symlink")
	}
}

func TestOpenRegularFIFODoesNotHang(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX FIFO; Windows special files need platform validation")
	}
	mkfifo, err := exec.LookPath("mkfifo")
	if err != nil {
		t.Skip("mkfifo required")
	}
	dir := t.TempDir()
	pipe := filepath.Join(dir, "pipe")
	if out, err := exec.Command(mkfifo, pipe).CombinedOutput(); err != nil {
		t.Fatalf("mkfifo: %v %s", err, out)
	}
	done := make(chan error, 1)
	go func() {
		f, err := openRegular(pipe)
		if err != nil {
			done <- err
			return
		}
		defer f.Close()
		st, err := f.Stat()
		if err != nil {
			done <- err
			return
		}
		if st.Mode().IsRegular() {
			done <- errors.New("FIFO reported as regular")
			return
		}
		done <- nil
	}()
	select {
	case err := <-done:
		if err != nil && err.Error() == "FIFO reported as regular" {
			t.Fatal(err)
		}
		// open may fail (ENXIO etc.) or succeed then fail IsRegular — both OK if timely
	case <-time.After(3 * time.Second):
		t.Fatal("openRegular blocked on FIFO")
	}
}

func TestAddFileDetectsReplacedInode(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "a.txt")
	if err := os.WriteFile(path, []byte("one"), 0o600); err != nil {
		t.Fatal(err)
	}
	// Hold the original inode open so the replacement cannot recycle it.
	held, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	info, err := held.Stat()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("two"), 0o600); err != nil {
		t.Fatal(err)
	}
	w := &walked{contents: map[string][]byte{}, executable: map[string]bool{}}
	err = w.addFile("a.txt", path, info, DefaultLimits)
	if err == nil || !strings.Contains(err.Error(), "changed while opening") {
		t.Fatalf("replaced inode must be refused with changed-while-opening, got %v", err)
	}
}

func TestAddFileDetectsSymlinkSwap(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("symlink swap + O_NOFOLLOW is Unix ADR-013")
	}
	root := t.TempDir()
	path := filepath.Join(root, "a.txt")
	if err := os.WriteFile(path, []byte("one"), 0o600); err != nil {
		t.Fatal(err)
	}
	info, err := os.Lstat(path)
	if err != nil {
		t.Fatal(err)
	}
	other := filepath.Join(root, "other.txt")
	if err := os.WriteFile(other, []byte("other"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(other, path); err != nil {
		t.Skipf("symlink: %v", err)
	}
	w := &walked{contents: map[string][]byte{}, executable: map[string]bool{}}
	err = w.addFile("a.txt", path, info, DefaultLimits)
	if err == nil {
		t.Fatal("path swapped to symlink must be refused")
	}
}
