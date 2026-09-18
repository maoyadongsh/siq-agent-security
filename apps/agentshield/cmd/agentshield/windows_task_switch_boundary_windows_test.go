package main

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/state"
)

// Hold only a fixture file with a real Windows FileShare.None handle. The
// helper has a bounded lifetime, no elevation and no execution-policy change.
func holdWindowsSwitchFile(t *testing.T, path string) func() {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	const script = `$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$file = [IO.File]::Open([Console]::In.ReadLine(), [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
try { [Console]::Out.WriteLine('SIQ_SWITCH_FILE_HELD'); [Console]::Out.Flush(); $null = [Console]::In.ReadLine() } finally { $file.Dispose() }`
	taskExe, err := windowsTaskExecutable()
	if err != nil {
		cancel()
		t.Fatal(err)
	}
	ps := filepath.Join(filepath.Dir(taskExe), "WindowsPowerShell", "v1.0", "powershell.exe")
	cmd := exec.CommandContext(ctx, ps, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encodeWindowsPowerShell(script))
	var diagnostic bytes.Buffer
	cmd.Stderr = &diagnostic
	in, err := cmd.StdinPipe()
	if err != nil {
		cancel()
		t.Fatal(err)
	}
	out, err := cmd.StdoutPipe()
	if err != nil {
		cancel()
		t.Fatal(err)
	}
	if err = cmd.Start(); err != nil {
		cancel()
		t.Fatal(err)
	}
	if _, err = io.WriteString(in, path+"\n"); err != nil {
		_ = in.Close()
		cancel()
		_ = cmd.Wait()
		t.Fatal(err)
	}
	line, err := bufio.NewReader(out).ReadString('\n')
	if err != nil || strings.TrimSpace(line) != "SIQ_SWITCH_FILE_HELD" {
		_ = in.Close()
		waitErr := cmd.Wait()
		cancel()
		t.Fatal("exclusive fixture lock not acquired", err, waitErr, diagnostic.String())
	}
	released := false
	release := func() {
		if released {
			return
		}
		released = true
		_ = in.Close()
		err := cmd.Wait()
		cancel()
		if err != nil {
			t.Error("fixture lock helper did not exit cleanly", err)
		}
	}
	t.Cleanup(release)
	return release
}

func TestWinSwitchBinaryBoundary(t *testing.T) {
	for _, side := range []string{"source", "target"} {
		for _, fault := range []string{"missing", "exclusive-lock"} {
			t.Run(side+"/"+fault, func(t *testing.T) {
				f := newWinTaskSwitchFixture(t)
				path := f.newPath
				if side == "source" {
					path = f.oldPath
				}
				original, err := os.ReadFile(path)
				if err != nil {
					t.Fatal(err)
				}
				restore := func() {
					if err := os.WriteFile(path, original, 0700); err != nil {
						t.Fatal(err)
					}
				}
				if fault == "missing" {
					if err = os.Remove(path); err != nil {
						t.Fatal(err)
					}
				} else {
					restore = holdWindowsSwitchFile(t, path)
					if _, err = os.ReadFile(path); err == nil {
						t.Fatal("fixture does not actually deny reads")
					}
				}
				local, err := os.ReadFile(filepath.Join(f.st.Dir, "windows-task.json"))
				if err != nil {
					t.Fatal(err)
				}
				if err = f.run("", io.Discard); err == nil {
					t.Fatal("inaccessible binary accepted")
				}
				if len(f.effects) != 0 || !bytes.Equal(f.xml, f.source) {
					t.Fatal("binary preflight failure stopped or changed source")
				}
				if err = f.st.CheckServiceSwitchPending(); err != nil {
					t.Fatal("failed binary preflight created a transaction", err)
				}
				after, err := os.ReadFile(filepath.Join(f.st.Dir, "windows-task.json"))
				if err != nil || !bytes.Equal(local, after) {
					t.Fatal("failed binary preflight changed signed record", err)
				}
				restore()
				if err = f.run("", io.Discard); err != nil {
					t.Fatal("valid candidate after boundary removal", err)
				}
			})
		}
	}
}

func TestWinSwitchRecoveryBinaryBoundary(t *testing.T) {
	for _, fault := range []string{"missing", "exclusive-lock"} {
		t.Run(fault, func(t *testing.T) {
			f := newWinTaskSwitchFixture(t)
			f.fault = "create-before"
			var output bytes.Buffer
			if err := f.run("", &output); err == nil {
				t.Fatal("fixture must interrupt after local apply")
			}
			id := winSwitchID(t, &output)
			f.fault = ""
			original, err := os.ReadFile(f.newPath)
			if err != nil {
				t.Fatal(err)
			}
			restore := func() {
				if err := os.WriteFile(f.newPath, original, 0700); err != nil {
					t.Fatal(err)
				}
			}
			if fault == "missing" {
				if err = os.Remove(f.newPath); err != nil {
					t.Fatal(err)
				}
			} else {
				restore = holdWindowsSwitchFile(t, f.newPath)
			}
			pending, err := os.ReadFile(filepath.Join(f.st.Dir, "service-switch.pending.json"))
			if err != nil {
				t.Fatal(err)
			}
			effects := strings.Join(f.effects, ",")
			if err = f.run(id, io.Discard); err == nil {
				t.Fatal("recovery accepted inaccessible target")
			}
			if effects != strings.Join(f.effects, ",") || f.xml != nil {
				t.Fatal("failed recovery mutated task")
			}
			after, err := os.ReadFile(filepath.Join(f.st.Dir, "service-switch.pending.json"))
			if err != nil || !bytes.Equal(pending, after) {
				t.Fatal("failed recovery changed pending proof", err)
			}
			restore()
			if err = f.run(id, io.Discard); err != nil {
				t.Fatal("explicit recovery after restoring target", err)
			}
		})
	}
}

func TestWinSwitchRollbackMissingBinary(t *testing.T) {
	f := newWinTaskSwitchFixture(t)
	var output bytes.Buffer
	if err := f.run("", &output); err != nil {
		t.Fatal(err)
	}
	id := winSwitchID(t, &output)
	old, err := os.ReadFile(f.oldPath)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.Remove(f.oldPath); err != nil {
		t.Fatal(err)
	}
	reverse := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: f.check.bindings.TargetSHA256, TargetSHA256: f.check.bindings.SourceSHA256}, targetPath: f.oldPath}
	effects := strings.Join(f.effects, ",")
	ok := func() error { return nil }
	if err = rollbackWindowsTask(f.st, f.host, id, f.source, "", io.Discard, ok, ok, reverse); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("missing rollback binary not refused", err)
	}
	if effects != strings.Join(f.effects, ",") || !f.running || !bytes.Equal(f.xml, f.target) {
		t.Fatal("missing rollback binary interrupted current version")
	}
	if err = os.WriteFile(f.oldPath, old, 0700); err != nil {
		t.Fatal(err)
	}
	if err = rollbackWindowsTask(f.st, f.host, id, f.source, "", io.Discard, ok, ok, reverse); err != nil {
		t.Fatal("restored valid rollback target", err)
	}
}
