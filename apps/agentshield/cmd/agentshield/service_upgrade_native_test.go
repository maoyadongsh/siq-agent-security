package main

import (
	"bytes"
	"crypto/sha256"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

// Opt-in native orchestration test. The trusted test build is copied to two
// locations; this is process/configuration switching, not a release signature
// or different-version compatibility claim.
func TestNativeUserServiceUpgrade(t *testing.T)                 { nativeUserServiceUpgrade(t, false) }
func TestNativeUserServiceUpgradeTransientFailure(t *testing.T) { nativeUserServiceUpgrade(t, true) }
func nativeUserServiceUpgrade(t *testing.T, transientFailure bool) {
	if runtime.GOOS != "linux" || os.Getenv("SIQ_TEST_UPGRADE_SYSTEMD") != "1" || os.Getenv("SIQ_TEST_BINARY") == "" {
		t.Skip("requires opt-in Linux manager and trusted native build")
	}
	dir := t.TempDir()
	raw, err := os.ReadFile(os.Getenv("SIQ_TEST_BINARY"))
	if err != nil {
		t.Fatal(err)
	}
	oldBinary, newBinary := filepath.Join(dir, "old binary"), filepath.Join(dir, "candidate binary")
	for _, path := range []string{oldBinary, newBinary} {
		if err = os.WriteFile(path, raw, 0700); err != nil {
			t.Fatal(err)
		}
	}
	pin := sha256.Sum256(raw)
	st, err := state.Open(filepath.Join(dir, "state"))
	if err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	listener.Close()
	w, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = st.Initialize(w, port); err != nil {
		w.Release()
		t.Fatal(err)
	}
	key, err := signing.Load(st.Dir)
	if err != nil {
		w.Release()
		t.Fatal(err)
	}
	source, err := renderUserUnit(oldBinary, st.Dir)
	if err != nil {
		w.Release()
		t.Fatal(err)
	}
	target, err := renderUserUnit(newBinary, st.Dir)
	if err != nil {
		w.Release()
		t.Fatal(err)
	}
	record, err := st.PrepareUserService(w, key, []byte(source))
	w.Release()
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(st.Dir, record.UnitName)
	if err = registerUserUnit(runUserSystemctl, path, record.UnitName, true); err != nil {
		t.Fatal(err)
	}
	defer func() {
		props, err := readUserUnit(runUserSystemctl, record.UnitName)
		if err != nil {
			t.Error(err)
			return
		}
		if err = verifyUserUnit(props, path, true); err != nil {
			t.Error("ownership changed; cleanup refused", err)
			return
		}
		if _, err = runUserSystemctl("stop", "--", record.UnitName); err != nil {
			t.Error(err)
			return
		}
		if err = unregisterUserUnit(runUserSystemctl, path, record.UnitName); err != nil {
			t.Error(err)
		}
	}()
	if _, err = runUserSystemctl("start", "--", record.UnitName); err != nil {
		t.Fatal(err)
	}
	ready := func() error {
		client := localClient()
		defer client.CloseIdleConnections()
		health, err := probeLocalInstance(client, fmt.Sprintf("http://127.0.0.1:%d", port), st)
		if err != nil {
			return err
		}
		if health.Version != Version {
			return fmt.Errorf("test build version mismatch")
		}
		return nil
	}
	deadline := time.Now().Add(12 * time.Second)
	for ready() != nil {
		if time.Now().After(deadline) {
			t.Fatal("source not ready")
		}
		time.Sleep(100 * time.Millisecond)
	}
	props, err := readUserUnit(runUserSystemctl, record.UnitName)
	if err != nil {
		t.Fatal(err)
	}
	oldPID := props["MainPID"]
	// Production CLI must reject the development issuer without interrupting
	// the running source. No trust-root override is added to the product.
	fixture, err := filepath.Abs("../../testdata/contracts/skill-manifest.v2.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	rejected := exec.Command(oldBinary, "service-upgrade", "--manifest", fixture, "--binary", newBinary, "--confirm-upgrade")
	rejected.Env = append(os.Environ(), "SIQ_AGENT_SECURITY_STATE_DIR="+st.Dir)
	if err = rejected.Run(); err == nil {
		t.Fatal("production CLI accepted development issuer")
	}
	props, err = readUserUnit(runUserSystemctl, record.UnitName)
	if err != nil || props["MainPID"] != oldPID {
		t.Fatal("invalid candidate interrupted source", err)
	}

	config, err := os.ReadFile(filepath.Join(st.Dir, "config.json"))
	if err != nil {
		t.Fatal(err)
	}
	recheck := func() error {
		raw, err := os.ReadFile(newBinary)
		if err != nil {
			return err
		}
		if sha256.Sum256(raw) != pin {
			return fmt.Errorf("test candidate changed")
		}
		return nil
	}
	control := userSystemctl(runUserSystemctl)
	var occupied *http.Server
	defer func() {
		if occupied != nil {
			_ = occupied.Close()
		}
	}()
	if transientFailure {
		inject := true
		control = func(args ...string) (string, error) {
			if args[0] == "start" && inject {
				inject = false
				listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
				if err != nil {
					return "", err
				}
				occupied = &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusServiceUnavailable) })}
				go func() { _ = occupied.Serve(listener) }()
			}
			return runUserSystemctl(args...)
		}
	}
	check := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: fmt.Sprintf("%x", pin), TargetSHA256: fmt.Sprintf("%x", pin)}, sourcePath: oldBinary, targetPath: newBinary}
	var output bytes.Buffer
	err = upgradeUserService(st, []byte(source), []byte(target), "", &output, control, recheck, ready, check)
	if transientFailure {
		if err == nil {
			t.Fatal("port conflict was reported as successful upgrade")
		}
		lines := strings.Split(strings.TrimSpace(output.String()), "\n")
		id := strings.TrimPrefix(lines[len(lines)-1], "切换事务：")
		if len(id) != 64 {
			t.Fatal("failed upgrade omitted recovery id")
		}
		if occupied == nil {
			t.Fatal("port conflict not injected")
		}
		if err = occupied.Close(); err != nil {
			t.Fatal(err)
		}
		deadline := time.Now().Add(10 * time.Second)
		for {
			props, err = readUserUnit(runUserSystemctl, record.UnitName)
			if err != nil {
				t.Fatal(err)
			}
			if props["ActiveState"] == "failed" && props["MainPID"] == "0" {
				break
			}
			if time.Now().After(deadline) {
				t.Fatal("failed candidate process did not exit")
			}
			time.Sleep(50 * time.Millisecond)
		}
		if err = upgradeUserService(st, []byte(source), []byte(target), id, io.Discard, runUserSystemctl, recheck, ready, check); err != nil {
			t.Fatal("transient failure recovery", err)
		}
	} else if err != nil {
		t.Fatal(err)
	}
	props, err = readUserUnit(runUserSystemctl, record.UnitName)
	if err != nil {
		t.Fatal(err)
	}
	if !serviceRunning(props) || props["MainPID"] == oldPID {
		t.Fatal("target process was not replaced")
	}
	if _, err = st.VerifyUserService(key, []byte(target)); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(filepath.Join(st.Dir, "config.json"))
	if err != nil || string(after) != string(config) {
		t.Fatal("config changed")
	}
	lines := strings.Split(strings.TrimSpace(output.String()), "\n")
	original := strings.TrimPrefix(lines[len(lines)-1], "切换事务：")
	// Successful output has an extra readiness line, so locate the explicit ID.
	for _, line := range lines {
		if strings.HasPrefix(line, "切换事务：") {
			original = strings.TrimPrefix(line, "切换事务：")
		}
	}
	priorCheck := func() error {
		raw, err := os.ReadFile(oldBinary)
		if err != nil {
			return err
		}
		if sha256.Sum256(raw) != pin {
			return fmt.Errorf("prior test binary changed")
		}
		return nil
	}
	if transientFailure {
		// A synthetic local snapshot of the pinned test build; production
		// SnapshotCurrent is covered separately, without a release trust bypass.
		snapshotDir := filepath.Join(st.Dir, "client-snapshots", fmt.Sprintf("%x", pin))
		if err = os.MkdirAll(snapshotDir, 0700); err != nil {
			t.Fatal(err)
		}
		originalBytes, err := os.ReadFile(oldBinary)
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(filepath.Join(snapshotDir, "siq-agent-security"), originalBytes, 0700); err != nil {
			t.Fatal(err)
		}
		if err = os.Remove(oldBinary); err != nil {
			t.Fatal(err)
		}
		plan, err := st.ReadServiceSwitch(key, original)
		if err != nil {
			t.Fatal(err)
		}
		verifyTestPin := func(_ string, path string) (string, error) {
			content, err := os.ReadFile(path)
			if err != nil {
				return "", err
			}
			if sha256.Sum256(content) != pin {
				return "", fmt.Errorf("test build identity mismatch")
			}
			return "test", nil
		}
		if _, _, err = prepareRollbackBinary(st, plan, oldBinary, "test-only", true, verifyTestPin); err != nil {
			t.Fatal("restore missing prior binary", err)
		}
	}
	if err = rollbackUserService(st, original, []byte(source), "", io.Discard, runUserSystemctl, priorCheck, ready, &serviceBinaryCheck{bindings: check.bindings, targetPath: oldBinary}); err != nil {
		t.Fatal("native source rollback", err)
	}
	if _, err = st.VerifyUserService(key, []byte(source)); err != nil {
		t.Fatal(err)
	}
	if err = ready(); err != nil {
		t.Fatal("rolled back service unhealthy", err)
	}

}
