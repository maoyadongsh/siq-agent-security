//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"
	"unsafe"

	"siq-agent-security/edge/agent/installplan"
)

func TestInteractiveConfirmationRequiresExactYesAndPreservesNextLine(t *testing.T) {
	p := &installplan.Plan{TenantID: "fixture-tenant", EnvironmentID: "fixture-env", ControlPlaneOrigin: "https://fixture.invalid", TargetArch: "arm64",
		Connectors: []installplan.Connector{{ID: "openclaw", Scope: installplan.Scope{Roots: []string{"/fixture/config"}, Include: []string{"openclaw.json"}}}}}
	for _, value := range []string{"yes\n", "yes\r\n", "\n", "y\n", "YES\n", "yes", "yes \n", strings.Repeat("x", 100) + "\n"} {
		input := strings.NewReader(value + "fixture-next-line\n")
		var out bytes.Buffer
		err := confirmInteractivePlan(context.Background(), input, &out, p, true)
		accepted := value == "yes\n" || value == "yes\r\n"
		if (err == nil) != accepted {
			t.Fatalf("confirmation mismatch for %q", value)
		}
		if accepted {
			rest, _ := io.ReadAll(input)
			if string(rest) != "fixture-next-line\n" {
				t.Fatal("confirmation consumed secret line")
			}
		}
		for _, text := range []string{"fixture-tenant", "fixture-env", "fixture.invalid", "/fixture/config", "openclaw.json", "true", "不授予智能体业务权限"} {
			if !strings.Contains(out.String(), text) {
				t.Fatal("scope not shown", text)
			}
		}
		if strings.Contains(out.String(), "fixture-next-line") {
			t.Fatal("input echoed")
		}
	}
}

type promptNotice struct {
	bytes.Buffer
	ready chan struct{}
	once  sync.Once
}

func (p *promptNotice) Write(data []byte) (int, error) {
	n, err := p.Buffer.Write(data)
	if strings.Contains(string(data), "输入不回显") {
		p.once.Do(func() { close(p.ready) })
	}
	return n, err
}
func (p *promptNotice) WriteString(data string) (int, error) { return p.Write([]byte(data)) }

func fixturePTY(t *testing.T) (*os.File, *os.File) {
	t.Helper()
	master, err := os.OpenFile("/dev/ptmx", os.O_RDWR|syscall.O_NOCTTY, 0)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { master.Close() })
	var unlock int32
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, master.Fd(), syscall.TIOCSPTLCK, uintptr(unsafe.Pointer(&unlock)))
	if errno != 0 {
		t.Fatal(errno)
	}
	var number uint32
	_, _, errno = syscall.Syscall(syscall.SYS_IOCTL, master.Fd(), syscall.TIOCGPTN, uintptr(unsafe.Pointer(&number)))
	if errno != 0 {
		t.Fatal(errno)
	}
	slave, err := os.OpenFile(fmt.Sprintf("/dev/pts/%d", number), os.O_RDWR|syscall.O_NOCTTY, 0)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { slave.Close() })
	return master, slave
}

func TestInteractiveEnrollmentMasksAndRestoresTerminal(t *testing.T) {
	for _, cancel := range []bool{false, true} {
		t.Run(fmt.Sprint(cancel), func(t *testing.T) {
			master, slave := fixturePTY(t)
			before, err := terminalState(slave)
			if err != nil {
				t.Fatal(err)
			}
			ctx, stop := context.WithCancel(context.Background())
			defer stop()
			out := &promptNotice{ready: make(chan struct{})}
			type result struct {
				code string
				err  error
			}
			done := make(chan result, 1)
			go func() { code, err := readInteractiveEnrollment(ctx, slave, out); done <- result{code, err} }()
			select {
			case <-out.ready:
			case <-time.After(3 * time.Second):
				t.Fatal("prompt missing")
			}
			during, err := terminalState(slave)
			if err != nil || during.Lflag&(syscall.ECHO|syscall.ECHONL) != 0 {
				t.Fatal("secret echo enabled")
			}
			if cancel {
				stop()
			} else if _, err := io.WriteString(master, "enr-fixture-secret\n"); err != nil {
				t.Fatal(err)
			}
			select {
			case result := <-done:
				if cancel {
					if !errors.Is(result.err, context.Canceled) || result.code != "" {
						t.Fatal("cancel failed")
					}
				} else if result.err != nil || result.code != "enr-fixture-secret" {
					t.Fatal("secret input failed")
				}
			case <-time.After(3 * time.Second):
				t.Fatal("input blocked")
			}
			after, err := terminalState(slave)
			if err != nil || after != before {
				t.Fatal("terminal was not restored")
			}
			if strings.Contains(out.String(), "enr-fixture") {
				t.Fatal("secret leaked")
			}
			if cancel {
				_, _ = io.WriteString(master, "fixture-unblock\n")
			}
		})
	}
}

func TestInteractiveRequiresTerminalAndNoFlagMixing(t *testing.T) {
	file, err := os.CreateTemp(t.TempDir(), "input")
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	if _, err := terminalState(file); err == nil {
		t.Fatal("file accepted as terminal")
	}
	for _, flags := range [][]string{{"--review-only"}, {"--confirm-plan-sha256", strings.Repeat("a", 64)}, {"--enrollment-code-stdin"}} {
		var out bytes.Buffer
		err := setupEnterprise(context.Background(), append([]string{"--interactive"}, flags...), &out)
		if err != errEnterpriseSetup || out.Len() != 0 {
			t.Fatal("mixed approval methods accepted")
		}
	}
}

func TestInteractiveOutputFailureAndCancelledConfirmationFailClosed(t *testing.T) {
	_, slave := fixturePTY(t)
	before, err := terminalState(slave)
	if err != nil {
		t.Fatal(err)
	}
	code, err := readInteractiveEnrollment(context.Background(), slave, failedSetupOutput{})
	if err == nil || code != "" {
		t.Fatal("failed prompt accepted")
	}
	after, err := terminalState(slave)
	if err != nil || after != before {
		t.Fatal("failed prompt left terminal modified")
	}
	p := &installplan.Plan{}
	if confirmInteractivePlan(context.Background(), strings.NewReader("yes\n"), failedSetupOutput{}, p, false) == nil {
		t.Fatal("invisible confirmation accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	var out bytes.Buffer
	if !errors.Is(confirmInteractivePlan(ctx, strings.NewReader("yes\n"), &out, p, false), context.Canceled) || out.Len() != 0 {
		t.Fatal("cancelled confirmation continued")
	}
}

type confirmationOutput struct {
	bytes.Buffer
	onPrompt func()
	called   bool
}

func (w *confirmationOutput) Write(data []byte) (int, error) {
	n, err := w.Buffer.Write(data)
	if !w.called && strings.Contains(string(data), "默认取消") {
		w.called = true
		w.onPrompt()
	}
	return n, err
}

func (w *confirmationOutput) WriteString(data string) (int, error) { return w.Write([]byte(data)) }

func TestInteractiveCLIStillRejectsUntrustedOrChangedPlanBeforeIdentity(t *testing.T) {
	for _, changed := range []bool{false, true} {
		t.Run(fmt.Sprint(changed), func(t *testing.T) {
			master, slave := fixturePTY(t)
			originalStdin := os.Stdin
			os.Stdin = slave
			defer func() { os.Stdin = originalStdin }()
			root := t.TempDir()
			stateDir := filepath.Join(root, "state")
			t.Setenv("SIQ_EDGE_STATE_DIR", stateDir)
			raw, err := os.ReadFile("installplan/testdata/plan.json")
			if err != nil {
				t.Fatal(err)
			}
			plan, err := installplan.Parse(raw)
			if err != nil {
				t.Fatal(err)
			}
			plan.TargetArch = runtime.GOARCH
			plan.IssuedAt = time.Now().Add(-time.Minute).UTC().Format(time.RFC3339)
			plan.ExpiresAt = time.Now().Add(10 * time.Minute).UTC().Format(time.RFC3339)
			raw, err = json.Marshal(plan)
			if err != nil {
				t.Fatal(err)
			}
			planPath, releasePath := filepath.Join(root, "plan.json"), filepath.Join(root, "release.json")
			if os.WriteFile(planPath, raw, 0600) != nil || os.WriteFile(releasePath, []byte(`{}`), 0600) != nil {
				t.Fatal("fixture")
			}
			out := &confirmationOutput{onPrompt: func() {
				if changed {
					if os.WriteFile(planPath, append(raw, '\n'), 0600) != nil {
						t.Error("fixture update")
					}
				}
				if _, err := io.WriteString(master, "yes\n"); err != nil {
					t.Error(err)
				}
			}}
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			err = setupEnterprise(ctx, []string{"--interactive", "--plan", planPath, "--release", releasePath,
				"--bundle", root, "--staging-parent", root, "--tenant", plan.TenantID, "--environment", plan.EnvironmentID,
				"--control-plane", plan.ControlPlaneOrigin}, out)
			want := "enterprise_setup_failed_at_prepare"
			if changed {
				want = "enterprise_setup_plan_changed"
			}
			if err == nil || err.Error() != want || !out.called {
				t.Fatalf("gate failed: %v", err)
			}
			if strings.Contains(out.String(), "输入不回显") {
				t.Fatal("secret requested before trust verification")
			}
			if _, err := os.Stat(stateDir); !os.IsNotExist(err) {
				t.Fatal("identity state written")
			}
		})
	}
}
