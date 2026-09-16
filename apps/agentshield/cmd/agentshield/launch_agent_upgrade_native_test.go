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
	"strconv"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

// Opt-in native orchestration on real launchd (GUI domain). The trusted test
// build is copied to two locations; this proves process/configuration
// switching and recovery, not release signatures or cross-version compatibility.
func TestNativeLaunchAgentUpgrade(t *testing.T)                 { nativeLaunchAgentUpgrade(t, false) }
func TestNativeLaunchAgentUpgradeTransientFailure(t *testing.T) { nativeLaunchAgentUpgrade(t, true) }
func nativeLaunchAgentUpgrade(t *testing.T, transientFailure bool) {
	if runtime.GOOS != "darwin" || os.Getenv("SIQ_TEST_UPGRADE_LAUNCHD") != "1" || os.Getenv("SIQ_TEST_BINARY") == "" {
		t.Skip("requires opt-in macOS launchd session and trusted native build")
	}
	root := os.Getenv("SIQ_TEST_STATE_ROOT")
	if root == "" {
		root = t.TempDir()
	} else {
		var err error
		root, err = os.MkdirTemp(root, "native-upgrade-*")
		if err != nil {
			t.Fatal(err)
		}
		defer os.RemoveAll(root)
	}
	root, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(os.Getenv("SIQ_TEST_BINARY"))
	if err != nil {
		t.Fatal(err)
	}
	binDir := filepath.Join(root, "bin")
	if err = os.Mkdir(binDir, 0700); err != nil {
		t.Fatal(err)
	}
	oldBinary, newBinary := filepath.Join(binDir, "old-siq-agent-security"), filepath.Join(binDir, "new-siq-agent-security")
	for _, path := range []string{oldBinary, newBinary} {
		if err = os.WriteFile(path, raw, 0700); err != nil {
			t.Fatal(err)
		}
	}
	pin := fmt.Sprintf("%x", sha256.Sum256(raw))
	st, err := state.Open(filepath.Join(root, "state"))
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
	instance, err := st.Initialize(w, port)
	if err != nil {
		w.Release()
		t.Fatal(err)
	}
	key, err := signing.Load(st.Dir)
	if err != nil {
		w.Release()
		t.Fatal(err)
	}
	source, err := renderLaunchAgent(oldBinary, st.Dir, instance.InstanceID)
	if err != nil {
		w.Release()
		t.Fatal(err)
	}
	target, err := renderLaunchAgent(newBinary, st.Dir, instance.InstanceID)
	if err != nil {
		w.Release()
		t.Fatal(err)
	}
	record, err := st.PrepareLaunchAgent(w, key, []byte(source))
	w.Release()
	if err != nil {
		t.Fatal(err)
	}
	home, uid, err := currentLaunchSession()
	if err != nil {
		t.Fatal(err)
	}
	host := launchAgentSwitchHost{home: home, uid: uid, control: runUserLaunchctl}
	sourceFile := mustResolve(t, filepath.Join(st.Dir, record.Label+".plist"))
	link, err := publishLaunchRegistration(home, sourceFile, record.Label)
	if err != nil {
		t.Fatal(err)
	}
	domain := "gui/" + strconv.Itoa(uid)
	defer func() {
		// Cleanup verifies ownership of whichever side is loaded before unloading.
		for _, side := range [][]byte{[]byte(target), []byte(source)} {
			loaded, _, err := inspectLaunchAgent(runUserLaunchctl, uid, record.Label, side, sourceFile)
			if err != nil || !loaded {
				continue
			}
			_, _ = runUserLaunchctl("bootout", domain+"/"+record.Label)
			break
		}
		if err := verifyLaunchRegistration(link, sourceFile); err == nil {
			_ = os.Remove(link)
		}
	}()
	if _, err = runUserLaunchctl("bootstrap", domain, link); err != nil {
		t.Fatal(err)
	}
	if _, err = runUserLaunchctl("kickstart", domain+"/"+record.Label); err != nil {
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
	deadline := time.Now().Add(15 * time.Second)
	for ready() != nil {
		if time.Now().After(deadline) {
			t.Fatal("source not ready")
		}
		time.Sleep(100 * time.Millisecond)
	}
	oldPID, err := readLoadedLaunchAgent(runUserLaunchctl, uid, []byte(source), sourceFile)
	if err != nil || oldPID == 0 {
		t.Fatal("source pid", oldPID, err)
	}
	// Production CLI must reject the development issuer without interrupting
	// the running source. No trust-root override exists in the product.
	fixture, err := filepath.Abs("../../testdata/contracts/skill-manifest.v2.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	rejected := exec.Command(oldBinary, "service-upgrade", "--manifest", fixture, "--binary", newBinary, "--confirm-upgrade")
	rejected.Env = append(os.Environ(), "SIQ_AGENT_SECURITY_STATE_DIR="+st.Dir)
	if out, err := rejected.CombinedOutput(); err == nil {
		t.Fatal("production CLI accepted development issuer", string(out))
	}
	pid, err := readLoadedLaunchAgent(runUserLaunchctl, uid, []byte(source), sourceFile)
	if err != nil || pid != oldPID {
		t.Fatal("invalid candidate interrupted source", pid, err)
	}
	config, err := os.ReadFile(filepath.Join(st.Dir, "config.json"))
	if err != nil {
		t.Fatal(err)
	}
	recheck := func() error {
		content, err := os.ReadFile(newBinary)
		if err != nil {
			return err
		}
		if fmt.Sprintf("%x", sha256.Sum256(content)) != pin {
			return fmt.Errorf("test candidate changed")
		}
		return nil
	}
	var occupied *http.Server
	defer func() {
		if occupied != nil {
			_ = occupied.Close()
		}
	}()
	if transientFailure {
		inject := true
		host.control = func(args ...string) (string, error) {
			if args[0] == "kickstart" && inject {
				inject = false
				listener, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
				if err != nil {
					return "", err
				}
				occupied = &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusServiceUnavailable) })}
				go func() { _ = occupied.Serve(listener) }()
			}
			return runUserLaunchctl(args...)
		}
	}
	check := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: pin, TargetSHA256: pin}, sourcePath: oldBinary, targetPath: newBinary}
	var output bytes.Buffer
	err = switchLaunchAgent(st, host, []byte(source), []byte(target), "", &output, recheck, ready, false, check)
	var id string
	for _, line := range strings.Split(output.String(), "\n") {
		if strings.HasPrefix(line, "切换事务：") {
			id = strings.TrimPrefix(line, "切换事务：")
		}
	}
	if len(id) != 64 {
		t.Fatal("no transaction id", output.String(), err)
	}
	if transientFailure {
		if err == nil {
			t.Fatal("port conflict was reported as successful upgrade")
		}
		if occupied == nil {
			t.Fatal("port conflict not injected")
		}
		if err = occupied.Close(); err != nil {
			t.Fatal(err)
		}
		deadline := time.Now().Add(10 * time.Second)
		for {
			rt, err := readLoadedLaunchRuntime(runUserLaunchctl, uid, []byte(target), sourceFile)
			if err != nil {
				t.Fatal(err)
			}
			if rt.PID == 0 && rt.LastExit != nil && *rt.LastExit != 0 {
				break
			}
			if time.Now().After(deadline) {
				t.Fatal("failed candidate process did not exit")
			}
			time.Sleep(100 * time.Millisecond)
		}
		host.control = runUserLaunchctl
		if err = switchLaunchAgent(st, host, []byte(source), []byte(target), id, io.Discard, recheck, ready, false, &serviceBinaryCheck{bindings: check.bindings, targetPath: newBinary}); err != nil {
			t.Fatal("transient failure recovery", err)
		}
	} else if err != nil {
		t.Fatal(err)
	}
	newPID, err := readLoadedLaunchAgent(runUserLaunchctl, uid, []byte(target), sourceFile)
	if err != nil || newPID == 0 || newPID == oldPID {
		t.Fatal("target process was not replaced", newPID, err)
	}
	if _, err = st.VerifyLaunchAgent(key, []byte(target)); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(filepath.Join(st.Dir, "config.json"))
	if err != nil || !bytes.Equal(after, config) {
		t.Fatal("config changed")
	}
	if err = ready(); err != nil {
		t.Fatal("upgraded service unhealthy", err)
	}
	priorCheck := func() error {
		content, err := os.ReadFile(oldBinary)
		if err != nil {
			return err
		}
		if fmt.Sprintf("%x", sha256.Sum256(content)) != pin {
			return fmt.Errorf("prior test binary changed")
		}
		return nil
	}
	if transientFailure {
		// Missing historical program restored from a synthetic local snapshot.
		snapshotDir := filepath.Join(st.Dir, "client-snapshots", pin)
		if err = os.MkdirAll(snapshotDir, 0700); err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(filepath.Join(snapshotDir, "siq-agent-security"), raw, 0700); err != nil {
			t.Fatal(err)
		}
		if err = os.Remove(oldBinary); err != nil {
			t.Fatal(err)
		}
		plan, err := st.ReadLaunchAgentSwitch(key, id)
		if err != nil {
			t.Fatal(err)
		}
		verifyTestPin := func(_ string, path string) (string, error) {
			content, err := os.ReadFile(path)
			if err != nil {
				return "", err
			}
			if fmt.Sprintf("%x", sha256.Sum256(content)) != pin {
				return "", fmt.Errorf("test build identity mismatch")
			}
			return "test", nil
		}
		render := func(path string) (string, error) { return renderLaunchAgent(path, st.Dir, instance.InstanceID) }
		if _, _, err = prepareHistoricalBinary(st, plan.BinaryBindings, plan.SourcePlist, render, oldBinary, "test-only", true, verifyTestPin); err != nil {
			t.Fatal("restore missing prior binary", err)
		}
	}
	back := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: pin, TargetSHA256: pin}, targetPath: oldBinary}
	if err = rollbackLaunchAgent(st, host, id, []byte(source), "", io.Discard, priorCheck, ready, back); err != nil {
		t.Fatal("native source rollback", err)
	}
	if _, err = st.VerifyLaunchAgent(key, []byte(source)); err != nil {
		t.Fatal(err)
	}
	rolledPID, err := readLoadedLaunchAgent(runUserLaunchctl, uid, []byte(source), sourceFile)
	if err != nil || rolledPID == 0 || rolledPID == newPID {
		t.Fatal("rolled back process not replaced", rolledPID, err)
	}
	if err = ready(); err != nil {
		t.Fatal("rolled back service unhealthy", err)
	}
	// Leave the job stopped and unregistered; the deferred cleanup verifies it.
	if err = stopRegisteredLaunchAgent(st, key, []byte(source), home, uid, runUserLaunchctl, 35*time.Second); err != nil {
		t.Fatal("final stop", err)
	}
	if err = unregisterLaunchAgent(st, key, []byte(source), home, uid, runUserLaunchctl); err != nil {
		t.Fatal("final unregister", err)
	}
	t.Logf("native launchd switch: old_pid=%d new_pid=%d rolled_pid=%d transaction=%s", oldPID, newPID, rolledPID, id)
}
