package skillmanifest

import (
	"context"
	"flag"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const windowsStageProbeArgument = "siq-owned-staged-executable-probe"
const windowsStageProbeMarker = "SIQ_OWNED_STAGED_EXE_OK\n"

func runWindowsStageProbe(args []string) {
	if len(args) != 2 || args[0] != windowsStageProbeArgument || !filepath.IsAbs(args[1]) {
		_, _ = io.WriteString(os.Stderr, "invalid staged probe arguments\n")
		os.Exit(2)
	}
	actual, err := os.Executable()
	if err != nil || !strings.EqualFold(filepath.Clean(actual), filepath.Clean(args[1])) {
		_, _ = io.WriteString(os.Stderr, "staged probe executable path mismatch\n")
		os.Exit(2)
	}
	if _, err := io.WriteString(os.Stdout, windowsStageProbeMarker); err != nil {
		os.Exit(2)
	}
	// This branch is entered only by the explicitly selected child test below;
	// bypass the test harness footer so stdout is exactly the fixed marker.
	os.Exit(0)
}

func TestStageVerifiedBinaryWindowsNativeExecutable(t *testing.T) {
	if args := flag.Args(); len(args) != 0 {
		runWindowsStageProbe(args)
		return
	}
	src, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	before, err := os.Lstat(src)
	if err != nil {
		t.Fatal(err)
	}
	if !before.Mode().IsRegular() || before.Mode()&0o111 != 0 {
		t.Fatal("native fixture must be an ordinary Windows executable without POSIX exec bits")
	}
	pin, err := HashFileDigest(src)
	if err != nil {
		t.Fatal(err)
	}
	stageRoot := filepath.Join(t.TempDir(), "stage")
	staged, err := StageVerifiedBinary(src, stageRoot, pin)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(staged, stageRoot+string(filepath.Separator)) ||
		!strings.EqualFold(filepath.Ext(staged), ".exe") || filepath.Base(staged) != filepath.Base(src) {
		t.Fatal("staged executable path must be a copy under the owned root")
	}
	after, err := os.Lstat(staged)
	if err != nil {
		t.Fatal(err)
	}
	if !after.Mode().IsRegular() || after.Size() != before.Size() || os.SameFile(before, after) {
		t.Fatal("staged executable must be a separate ordinary copy of the pinned size")
	}
	if got, err := HashFileDigest(staged); err != nil || got != pin {
		t.Fatal("staged executable digest differs from pin")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, staged,
		"-test.run=^TestStageVerifiedBinaryWindowsNativeExecutable$", "-test.count=1",
		"--", windowsStageProbeArgument, staged)
	cmd.WaitDelay = time.Second
	output, err := cmd.Output()
	if ctx.Err() != nil {
		t.Fatal("owned staged probe timed out")
	}
	if err != nil || string(output) != windowsStageProbeMarker || cmd.ProcessState == nil ||
		!cmd.ProcessState.Exited() || cmd.ProcessState.ExitCode() != 0 {
		t.Fatalf("owned staged probe failed: error_type=%T stdout_bytes=%d", err, len(output))
	}
	if got, err := HashFileDigest(src); err != nil || got != pin {
		t.Fatal("native source changed during staging or probe")
	}
	if got, err := HashFileDigest(staged); err != nil || got != pin {
		t.Fatal("staged executable changed during probe")
	}
	t.Logf("owned staged Windows probe: exact marker, exit 0, bytes=%d sha256=%s", before.Size(), pin)
}

func TestStageVerifiedBinaryWindowsPinMismatchBeforeStage(t *testing.T) {
	src, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	before, err := HashFileDigest(src)
	if err != nil {
		t.Fatal(err)
	}
	wrong := strings.Repeat("0", 64)
	if wrong == before {
		wrong = strings.Repeat("1", 64)
	}
	stageRoot := filepath.Join(t.TempDir(), "must-not-exist")
	staged, err := StageVerifiedBinary(src, stageRoot, wrong)
	if staged != "" || err == nil || !strings.HasPrefix(err.Error(), "skillmanifest: source sha256 ") {
		t.Fatal("native wrong pin must reach digest rejection, not the POSIX no-exec guard")
	}
	if _, err := os.Lstat(stageRoot); !os.IsNotExist(err) {
		t.Fatal("native wrong pin created a staging root")
	}
	if after, err := HashFileDigest(src); err != nil || after != before {
		t.Fatal("native wrong pin changed source bytes")
	}
}
