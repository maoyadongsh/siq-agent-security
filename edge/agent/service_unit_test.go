package main

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestRenderUserService(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("Linux service")
	}
	unit, err := renderUserService("/opt/siq agent/edge-agent", "/home/fixture/.siq-edge", "/opt/siq agent/connectors")
	if err != nil {
		t.Fatal(err)
	}
	for _, value := range []string{`ExecStart="/opt/siq agent/edge-agent" serve`, "NoNewPrivileges=yes", "UMask=0077", "KillMode=control-group", "WantedBy=default.target"} {
		if !strings.Contains(unit, value) {
			t.Fatalf("missing %s", value)
		}
	}
	for _, value := range []string{"sudo", "User=root", "enable-linger", "enrollment", "secret", "EnvironmentFile"} {
		if strings.Contains(unit, value) {
			t.Fatalf("unexpected %s", value)
		}
	}
}

func TestServiceUnitRejectsInjection(t *testing.T) {
	for _, bad := range []string{"", "/", "relative", "/opt/../bin", "/opt//bin", "/opt/bin/", "/opt/%h", "/opt/$HOME", "/opt/\"evil", "/opt/\nExecStart=/bin/true", "/opt/\x00", "/opt/\\bin"} {
		for position := 0; position < 3; position++ {
			paths := []string{"/opt/siq/edge", "/home/fixture/.siq-edge", "/opt/siq/connectors"}
			paths[position] = bad
			if _, err := renderUserService(paths[0], paths[1], paths[2]); err == nil {
				t.Fatalf("accepted invalid path at %d", position)
			}
		}
	}
}

func TestServiceUnitOnlyWritesProvidedOutput(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("Linux service")
	}
	var output bytes.Buffer
	if err := writeServiceUnit([]string{"--binary", "/opt/siq/edge", "--state-dir", "/home/fixture/.siq-edge", "--connector-dir", "/opt/siq/connectors"}, &output); err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(output.String(), "[Unit]") {
		t.Fatal("no unit")
	}
	if err := writeServiceUnit([]string{"extra"}, &output); err == nil {
		t.Fatal("accepted positional argument")
	}
}

func TestServiceUnitSystemdSyntax(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("Linux service")
	}
	analyzer, err := exec.LookPath("systemd-analyze")
	if err != nil {
		t.Skip("systemd-analyze not installed")
	}
	dir := t.TempDir()
	binary, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	// Exercise a real existing executable path with spaces, not just a string assertion.
	spaced := filepath.Join(dir, "edge agent")
	if err := os.Symlink(binary, spaced); err != nil {
		t.Fatal(err)
	}
	binary = spaced
	unit, err := renderUserService(binary, dir, dir)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "siq-edge-test.service")
	if err := os.WriteFile(path, []byte(unit), 0600); err != nil {
		t.Fatal(err)
	}
	// Offline parsing only: never contacts systemd or starts the unit.
	cmd := exec.Command(analyzer, "verify", "--man=no", path)
	cmd.Env = append(os.Environ(), "SYSTEMD_LOG_LEVEL=err")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("unit syntax failed: %v: %s", err, out)
	}
}
