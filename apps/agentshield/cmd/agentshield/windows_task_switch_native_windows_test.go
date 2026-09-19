package main

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/clientrelease"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

// Explicit opt-in: two locally built test versions and an isolated Task
// Scheduler instance. No release trust-root override or paid model is used.
// This proves native process/configuration switching, not official publishing.
func TestWinTaskSwitchNative(t *testing.T) {
	if os.Getenv("SIQ_TEST_WINDOWS_SWITCH") != "1" {
		t.Skip("requires explicit isolated Windows task switch opt-in")
	}
	oldPath, newPath := os.Getenv("SIQ_TEST_WINDOWS_SOURCE"), os.Getenv("SIQ_TEST_WINDOWS_TARGET")
	oldVersion, newVersion := os.Getenv("SIQ_TEST_WINDOWS_SOURCE_VERSION"), os.Getenv("SIQ_TEST_WINDOWS_TARGET_VERSION")
	if oldPath == "" || newPath == "" || oldVersion == "" || newVersion == "" || oldVersion == newVersion {
		t.Fatal("two distinct test versions required")
	}
	oldHash, err := clientrelease.Digest(oldPath)
	if err != nil {
		t.Fatal(err)
	}
	newHash, err := clientrelease.Digest(newPath)
	if err != nil {
		t.Fatal(err)
	}
	if oldHash == newHash {
		t.Fatal("distinct native artifacts required")
	}
	dir, err := os.MkdirTemp(os.Getenv("TEMP"), "task-switch-native-")
	if err != nil {
		t.Fatal(err)
	}
	// Retain this private directory for recovery/evidence even when a test fails.
	t.Logf("isolated retained state: %s", dir)
	st, err := state.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	_ = listener.Close()
	w, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = st.Initialize(w, port); err != nil {
		_ = w.Release()
		t.Fatal(err)
	}
	key, err := signing.Load(st.Dir)
	if err != nil {
		_ = w.Release()
		t.Fatal(err)
	}
	instance, err := st.ReadLocalInstance()
	if err != nil {
		_ = w.Release()
		t.Fatal(err)
	}
	host, err := currentWindowsTaskSwitchHost()
	if err != nil {
		_ = w.Release()
		t.Fatal(err)
	}
	sourceText, err := renderWindowsTask(oldPath, st.Dir, instance.InstanceID, host.sid)
	if err != nil {
		_ = w.Release()
		t.Fatal(err)
	}
	targetText, err := renderWindowsTask(newPath, st.Dir, instance.InstanceID, host.sid)
	if err != nil {
		_ = w.Release()
		t.Fatal(err)
	}
	source, target := []byte(sourceText), []byte(targetText)
	record, err := st.PrepareWindowsTask(w, key, source, host.sid)
	if err != nil {
		_ = w.Release()
		t.Fatal(err)
	}
	lifecycle, err := state.AcquireScopedWriter(st.Dir, "service-control")
	if err != nil {
		_ = w.Release()
		t.Fatal(err)
	}
	// Cleanup never guesses task ownership or force-kills a process. An unknown
	// or incomplete transaction is retained and explicitly reported for recovery.
	t.Cleanup(func() {
		if err := st.CheckServiceSwitchPending(); err != nil {
			t.Error("cleanup retained pending transaction", err)
			return
		}
		var current []byte
		for _, xml := range [][]byte{source, target} {
			if _, err := st.VerifyWindowsTask(key, xml, host.sid); err == nil {
				current = xml
				break
			}
		}
		if current == nil {
			t.Error("cleanup refused unknown local task")
			return
		}
		lock, err := state.AcquireScopedWriter(st.Dir, "service-control")
		if err != nil {
			t.Error(err)
			return
		}
		defer lock.Release()
		if err = host.stop(st, key, current); err != nil {
			t.Error("cleanup stop", err)
			return
		}
		writer, err := state.AcquireWriter(st.Dir)
		if err != nil {
			t.Error(err)
			return
		}
		defer writer.Release()
		if err = unregisterOwnedWindowsTask(st, key, current, host.sid, host.presence, host.query, host.runtime, host.remove); err != nil {
			t.Error("cleanup unregister", err)
			return
		}
		if exists, err := host.presence(record.TaskName, host.sid); err != nil || exists {
			t.Error("cleanup absence unconfirmed", err)
			return
		}
		t.Log("native task stopped and unregistered; private evidence retained")
	})
	err = registerOwnedWindowsTask(st, key, source, host.sid, host.presence, host.query, host.create, io.Discard)
	err = errors.Join(err, w.Release(), lifecycle.Release())
	if err != nil {
		t.Fatal(err)
	}
	readyOld, readyNew := versionReady(st, oldVersion, "native-test"), versionReady(st, newVersion, "native-test")
	startLock, err := state.AcquireScopedWriter(st.Dir, "service-control")
	if err != nil {
		t.Fatal(err)
	}
	err = startOwnedWindowsTask(st, key, source, host.sid, host.query, host.start, readyOld, host.wait)
	err = errors.Join(err, startLock.Release())
	if err != nil {
		t.Fatal(err)
	}
	// The public CLI must reject an untrusted candidate without stopping source.
	manifest, err := filepath.Abs("../../testdata/contracts/skill-manifest.v2.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	rejected := exec.Command(oldPath, "service-upgrade", "--manifest", manifest, "--binary", newPath, "--confirm-upgrade")
	for _, entry := range os.Environ() {
		name, _, _ := strings.Cut(entry, "=")
		if !strings.EqualFold(name, product.EnvStateDir) && !strings.EqualFold(name, "AGENTSHIELD_STATE_DIR") {
			rejected.Env = append(rejected.Env, entry)
		}
	}
	rejected.Env = append(rejected.Env, product.EnvStateDir+"="+st.Dir)
	rejection, err := rejected.CombinedOutput()
	if err == nil || !strings.Contains(string(rejection), "skillmanifest: untrusted signing identity") {
		t.Fatal("production CLI did not reject the fixture signing identity", err)
	}
	if err = readyOld(); err != nil {
		t.Fatal("rejected candidate interrupted source", err)
	}
	config, err := os.ReadFile(filepath.Join(st.Dir, "config.json"))
	if err != nil {
		t.Fatal(err)
	}
	check := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: oldHash, TargetSHA256: newHash}, sourcePath: oldPath, targetPath: newPath}
	// The test driver verifies exact local build hashes, never substitutes a
	// production release key. Real task operations below all use product code.
	recheck := func() error { return check.target() }
	injected := host
	injected.create = func(name, sid string, xml []byte) error {
		if err := host.create(name, sid, xml); err != nil {
			return err
		}
		return errors.New("test driver injected lost response after actual target creation")
	}
	var out bytes.Buffer
	if err = switchWindowsTask(st, injected, source, target, "", &out, recheck, readyNew, check); err == nil {
		t.Fatal("injected lost response reported success")
	}
	id := winSwitchID(t, &out)
	if st.CheckServiceSwitchPending() == nil {
		t.Fatal("lost response cleared startup barrier")
	}
	if err = startOwnedWindowsTask(st, key, target, host.sid, host.query, host.start, readyNew, 0); err == nil {
		t.Fatal("ordinary start bypassed incomplete transaction")
	}
	observed, err := host.inspect(record.TaskName, source, target)
	if err != nil || observed.side != "target" || observed.runtime.State != "ready" {
		t.Fatal("native target not idle after interrupted create", err)
	}
	if err = switchWindowsTask(st, host, source, target, id, io.Discard, recheck, readyNew, check); err != nil {
		t.Fatal("native recovery", err)
	}
	if err = readyNew(); err != nil {
		t.Fatal(err)
	}
	if err = switchWindowsTask(st, host, source, target, id, io.Discard, recheck, readyNew, check); err != nil {
		t.Fatal("native idempotent reuse", err)
	}
	reverse := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: newHash, TargetSHA256: oldHash}, targetPath: oldPath}
	if err = rollbackWindowsTask(st, host, id, source, "", io.Discard, reverse.target, readyOld, reverse); err != nil {
		t.Fatal("native rollback", err)
	}
	if err = readyOld(); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(filepath.Join(st.Dir, "config.json"))
	if err != nil || !bytes.Equal(config, after) {
		t.Fatal("configuration changed during version switch", err)
	}
	t.Logf("native source %s -> target %s -> source %s; source_sha256=%s target_sha256=%s", oldVersion, newVersion, oldVersion, oldHash, newHash)
	t.Log(fmt.Sprintf("forward transaction %s completed; source rejected untrusted CLI candidate; interrupted native create recovered", id))
}
