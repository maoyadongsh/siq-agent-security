package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"io"
	"io/fs"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/clientrelease"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

// Explicit opt-in: two locally built test versions and an isolated Task
// Scheduler instance. No release trust-root override or paid model is used.
// This proves native process/configuration switching, not official publishing.
func TestWinTaskSwitchNativeBoundary(t *testing.T) {
	if os.Getenv("SIQ_TEST_WINDOWS_BOUNDARY") != "1" {
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
	dir, err := os.MkdirTemp(os.Getenv("TEMP"), "task-boundary-native-")
	if err != nil {
		t.Fatal(err)
	}
	// Retain this private directory for recovery/evidence even when a test fails.
	t.Logf("isolated retained state: %s", dir)
	// Operate only on private copies; do not exclusively lock shared build artifacts.
	oldPath = copyWindowsBoundaryBinary(t, oldPath, filepath.Join(dir, "source.exe"))
	newPath = copyWindowsBoundaryBinary(t, newPath, filepath.Join(dir, "target.exe"))
	st, err := state.Open(filepath.Join(dir, "state"))
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
	assertRevoked := seedWindowsSwitchRevocation(t, st, key, oldPath)
	stops := 0
	originalStop := host.stop
	host.stop = func(s *state.Store, k *signing.Key, xml []byte) error {
		stops++
		if err := originalStop(s, k, xml); err != nil {
			return err
		}
		binary := oldPath
		if bytes.Equal(xml, target) {
			binary = newPath
		}
		assertRevoked(binary)
		return nil
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
	check := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: oldHash, TargetSHA256: newHash}, sourcePath: oldPath, targetPath: newPath}
	recheck := check.target
	// An actual target read lock must reject before the running source stops.
	release := holdWindowsSwitchFile(t, newPath)
	if err = switchWindowsTask(st, host, source, target, "", io.Discard, recheck, readyNew, check); err == nil {
		t.Fatal("exclusive target lock accepted")
	}
	if stops != 0 {
		t.Fatal("target lock interrupted the source")
	}
	if err = readyOld(); err != nil {
		t.Fatal("source unhealthy after lock rejection", err)
	}
	if err = st.CheckServiceSwitchPending(); err != nil {
		t.Fatal("lock rejection created a transaction", err)
	}
	release()
	// Delete only the private candidate copy, then restore the same pinned bytes.
	candidate, err := os.ReadFile(newPath)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.Remove(newPath); err != nil {
		t.Fatal(err)
	}
	if err = switchWindowsTask(st, host, source, target, "", io.Discard, recheck, readyNew, check); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("missing target not refused", err)
	}
	if stops != 0 {
		t.Fatal("missing target interrupted the source")
	}
	if err = readyOld(); err != nil {
		t.Fatal("source unhealthy after missing target rejection", err)
	}
	if err = st.CheckServiceSwitchPending(); err != nil {
		t.Fatal("missing target created a transaction", err)
	}
	if err = os.WriteFile(newPath, candidate, 0700); err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	if err = switchWindowsTask(st, host, source, target, "", &output, recheck, readyNew, check); err != nil {
		t.Fatal("native forward switch", err)
	}
	id := winSwitchID(t, &output)
	if err = readyNew(); err != nil {
		t.Fatal(err)
	}
	reverse := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: newHash, TargetSHA256: oldHash}, targetPath: oldPath}
	if err = rollbackWindowsTask(st, host, id, source, "", io.Discard, reverse.target, readyOld, reverse); err != nil {
		t.Fatal("native rollback", err)
	}
	if err = readyOld(); err != nil {
		t.Fatal(err)
	}
	if stops != 2 {
		t.Fatal("unexpected native stop count", stops)
	}
	t.Logf("native boundary verified: target exclusive-lock and missing rejected before stop; source %s -> target %s -> source; revoked draft remains denied in stopped-version CLI probes", oldVersion, newVersion)
}

func copyWindowsBoundaryBinary(t *testing.T, source, target string) string {
	t.Helper()
	raw, err := os.ReadFile(source)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(target, raw, 0700); err != nil {
		t.Fatal(err)
	}
	return target
}

func windowsBoundaryCLI(t *testing.T, binary, stateDir string, want int, args ...string) []byte {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, binary, args...)
	for _, entry := range os.Environ() {
		name, _, _ := strings.Cut(entry, "=")
		if strings.EqualFold(name, product.EnvStateDir) || strings.EqualFold(name, "AGENTSHIELD_STATE_DIR") || strings.EqualFold(name, product.EnvSigningSeed) || strings.EqualFold(name, product.EnvSigningSeedOld) {
			continue
		}
		cmd.Env = append(cmd.Env, entry)
	}
	cmd.Env = append(cmd.Env, product.EnvStateDir+"="+stateDir)
	output, err := cmd.CombinedOutput()
	actual := 0
	if err != nil {
		var exit *exec.ExitError
		if !errors.As(err, &exit) {
			t.Fatal("test CLI could not execute", err)
		}
		actual = exit.ExitCode()
	}
	if actual != want {
		t.Fatalf("test CLI %s exit=%d expected=%d: %s", args[0], actual, want, output)
	}
	return output
}

// Create and revoke a real CLI declaration. No model approval, effective grant
// or historically deployed permission is invented by this fixture.
func seedWindowsSwitchRevocation(t *testing.T, st *state.Store, key *signing.Key, binary string) func(string) {
	t.Helper()
	skill := t.TempDir()
	if err := os.WriteFile(filepath.Join(skill, "SKILL.md"), []byte("---\nname: windows-switch-revocation\ndescription: Read a harmless isolated test fixture.\n---\nRead-only prose.\n"), 0600); err != nil {
		t.Fatal(err)
	}
	var admitted struct {
		AdmissionID string `json:"admission_id"`
	}
	if err := json.Unmarshal(windowsBoundaryCLI(t, binary, st.Dir, 0, "admit", skill), &admitted); err != nil || admitted.AdmissionID == "" {
		t.Fatal("admission fixture", err)
	}
	var created struct {
		Grant    grant.Grant `json:"grant"`
		Revision int         `json:"state_revision"`
	}
	if err := json.Unmarshal(windowsBoundaryCLI(t, binary, st.Dir, 0, "grant", admitted.AdmissionID, "--platform", "hermes", "--subject", "windows-switch-revocation"), &created); err != nil || created.Grant.GrantID == "" {
		t.Fatal("grant fixture", err)
	}
	var revoked struct {
		Grant    grant.Grant `json:"grant"`
		Revision int         `json:"state_revision"`
	}
	if err := json.Unmarshal(windowsBoundaryCLI(t, binary, st.Dir, 0, "grant", "revoke", created.Grant.GrantID), &revoked); err != nil || revoked.Grant.Status != "revoked" || revoked.Revision <= created.Revision {
		t.Fatal("revocation fixture", err)
	}
	snapshot := func() map[string][32]byte {
		result := map[string][32]byte{}
		for _, namespace := range []string{"admissions", "grants", "policies", "commits"} {
			err := filepath.WalkDir(filepath.Join(st.Dir, namespace), func(path string, entry fs.DirEntry, err error) error {
				if err != nil {
					return err
				}
				if entry.IsDir() {
					return nil
				}
				if !entry.Type().IsRegular() {
					return errors.New("unexpected business fixture file type")
				}
				raw, err := os.ReadFile(path)
				if err != nil {
					return err
				}
				rel, err := filepath.Rel(st.Dir, path)
				if err != nil {
					return err
				}
				result[rel] = sha256.Sum256(raw)
				return nil
			})
			if err != nil {
				t.Fatal(err)
			}
		}
		return result
	}
	before := snapshot()
	assert := func(executable string) {
		t.Helper()
		current, revision, err := st.GetGrantWithSeq(revoked.Grant.GrantID)
		if err != nil || revision != revoked.Revision || current.Status != "revoked" || !grant.Verify(key.Public(), *current) {
			t.Fatal("revocation identity, signature or revision changed", err)
		}
		if st.ActiveGrant("hermes", "windows-switch-revocation") != nil {
			t.Fatal("revoked grant became active")
		}
		for _, action := range []struct{ command, reason string }{{"challenge", "cannot challenge status revoked"}, {"deploy", "illegal transition revoked"}} {
			output := windowsBoundaryCLI(t, executable, st.Dir, 1, "grant", action.command, revoked.Grant.GrantID)
			if !strings.Contains(string(output), action.reason) {
				t.Fatalf("expected revoked %s denial was not observed: %s", action.command, output)
			}
		}
		if !reflect.DeepEqual(before, snapshot()) {
			t.Fatal("upgrade/rollback/denial modified business history")
		}
		t.Logf("revoked CLI draft verified: revision=%d business_files=%d; challenge/deploy denied without mutation", revoked.Revision, len(before))
	}
	assert(binary)
	return assert
}
