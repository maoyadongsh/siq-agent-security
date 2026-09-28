package main

import (
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/state"
	"syscall"
	"testing"
	"time"
)

func TestServeStateDirectorySelection(t *testing.T) {
	selected := t.TempDir()
	ambient := filepath.Join(t.TempDir(), "ambient")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", ambient)
	if got, err := serveStateDirectory(selected, true); err != nil || got != selected {
		t.Fatal(got, err)
	}
	if got, err := serveStateDirectory("", false); err != nil || got != ambient {
		t.Fatal(got, err)
	}
	t.Run("symlink", func(t *testing.T) {
		link := filepath.Join(t.TempDir(), "alias")
		if err := os.Symlink(selected, link); err != nil {
			if runtime.GOOS == "windows" && errors.Is(err, syscall.Errno(1314)) {
				t.Skip("Windows symlink privilege unavailable; junction tests run separately")
			}
			t.Fatal(err)
		}
		if _, err := serveStateDirectory(link, true); err == nil {
			t.Fatal("accepted symlink")
		}
	})
	file := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(file, []byte("original"), 0600); err != nil {
		t.Fatal(err)
	}
	for _, invalid := range []string{"", "relative", selected + string(os.PathSeparator) + ".", file, ambient} {
		if _, err := serveStateDirectory(invalid, true); err == nil {
			t.Fatal("accepted invalid directory", invalid)
		}
	}
	for _, args := range [][]string{{"--state-dir", ""}, {"--state-dir", ambient}, {"--state-dir", selected, "unexpected"}} {
		if err := cmdServe(args); err == nil {
			t.Fatal("invalid serve accepted")
		}
	}
	if _, err := os.Lstat(ambient); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("ambient directory created", err)
	}
	if os.Getenv("SIQ_AGENT_SECURITY_STATE_DIR") != ambient {
		t.Fatal("environment mutated")
	}
}

func TestNativeServeExplicitDirectory(t *testing.T) {
	if runtime.GOOS != "linux" || os.Getenv("SIQ_TEST_SERVE_DIRECTORY") != "1" {
		t.Skip("isolated Linux subprocess opt-in required")
	}
	binary := os.Getenv("SIQ_TEST_BINARY")
	if binary == "" {
		t.Fatal("binary required")
	}
	selected := t.TempDir()
	ambient := filepath.Join(t.TempDir(), "ambient")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", ambient)
	t.Setenv("AGENTSHIELD_STATE_DIR", ambient)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	_ = ln.Close()
	st, err := state.Open(selected)
	if err != nil {
		t.Fatal(err)
	}
	writer, err := state.AcquireWriter(selected)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := st.Initialize(writer, port); err != nil {
		t.Fatal(err)
	}
	if err := writer.Release(); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(binary, "serve", "--state-dir", selected)
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	defer func() {
		_ = cmd.Process.Signal(os.Interrupt)
		select {
		case err := <-done:
			if err != nil {
				t.Error("serve did not exit cleanly", err)
			}
		case <-time.After(10 * time.Second):
			_ = cmd.Process.Kill()
			<-done
			t.Error("serve shutdown timed out")
		}
	}()
	client := localClient()
	defer client.CloseIdleConnections()
	deadline := time.Now().Add(10 * time.Second)
	for {
		if _, err = probeLocalInstance(client, fmt.Sprintf("http://127.0.0.1:%d", port), st); err == nil {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("selected instance not ready", err)
		}
		time.Sleep(50 * time.Millisecond)
	}
	if _, err := os.Lstat(ambient); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("ambient directory touched", err)
	}
	if _, err := os.Stat(filepath.Join(selected, state.LockFile)); err != nil {
		t.Fatal("selected writer missing", err)
	}
}
