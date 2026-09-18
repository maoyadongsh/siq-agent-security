package main

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

// This controller is an orchestration fixture, not native Task Scheduler evidence.
type winTaskSwitchFixture struct {
	t                *testing.T
	st               *state.Store
	key              *signing.Key
	source, target   []byte
	oldPath, newPath string
	check            *serviceBinaryCheck
	host             windowsTaskSwitchHost
	xml              []byte
	running, queued  bool
	fault            string
	effects          []string
}

func newWinTaskSwitchFixture(t *testing.T) *winTaskSwitchFixture {
	t.Helper()
	s, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(s.Dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	key, err := signing.Load(s.Dir)
	if err != nil {
		t.Fatal(err)
	}
	instance, err := s.ReadLocalInstance()
	if err != nil {
		t.Fatal(err)
	}
	const sid = "S-1-5-21-100-200-300-1001"
	source, err := renderWindowsTask(`C:\SIQ\old.exe`, `C:\SIQ\state`, instance.InstanceID, sid)
	if err != nil {
		t.Fatal(err)
	}
	target, err := renderWindowsTask(`C:\SIQ\new.exe`, `C:\SIQ\state`, instance.InstanceID, sid)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.PrepareWindowsTask(w, key, []byte(source), sid); err != nil {
		t.Fatal(err)
	}
	if err = w.Release(); err != nil {
		t.Fatal(err)
	}
	binDir := t.TempDir()
	oldPath, newPath := filepath.Join(binDir, "old.exe"), filepath.Join(binDir, "new.exe")
	for p, contents := range map[string]string{oldPath: "old executable fixture", newPath: "new executable fixture"} {
		if err = os.WriteFile(p, []byte(contents), 0700); err != nil {
			t.Fatal(err)
		}
	}
	a, b := sha256.Sum256([]byte("old executable fixture")), sha256.Sum256([]byte("new executable fixture"))
	f := &winTaskSwitchFixture{t: t, st: s, key: key, source: []byte(source), target: []byte(target), oldPath: oldPath, newPath: newPath, xml: []byte(source)}
	f.check = &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: fmt.Sprintf("%x", a), TargetSHA256: fmt.Sprintf("%x", b)}, sourcePath: oldPath, targetPath: newPath}
	name := `\SIQ-Agent-Security-` + instance.InstanceID
	identity := func(n, u string) {
		if n != name || u != sid {
			t.Fatal("foreign task or user")
		}
	}
	locked := func() {
		for _, scope := range []string{"", "service-control"} {
			var probe *state.Writer
			var err error
			if scope == "" {
				probe, err = state.AcquireWriter(s.Dir)
			} else {
				probe, err = state.AcquireScopedWriter(s.Dir, scope)
			}
			if err == nil {
				_ = probe.Release()
				t.Fatal("mutation lacks exclusive writer", scope)
			}
			if !errors.Is(err, state.ErrWriterBusy) {
				t.Fatal("unexpected lock error", err)
			}
		}
		if s.CheckServiceSwitchPending() == nil {
			t.Fatal("external mutation without startup barrier")
		}
	}
	f.host = windowsTaskSwitchHost{sid: sid}
	f.host.presence = func(n, u string) (bool, error) {
		identity(n, u)
		if f.fault == "presence" {
			return false, errors.New("fixture presence")
		}
		return f.xml != nil, nil
	}
	f.host.query = func(n string) ([]byte, error) {
		identity(n, sid)
		if f.fault == "query" {
			return nil, errors.New("fixture query")
		}
		return f.xml, nil
	}
	f.host.runtime = func(n, u string) (string, error) {
		identity(n, u)
		if f.fault == "runtime" {
			return "", errors.New("fixture runtime")
		}
		if f.queued {
			return "SIQ_TASK_RUNTIME:2:0:0", nil
		}
		if f.running {
			return "SIQ_TASK_RUNTIME:4:1:0", nil
		}
		return "SIQ_TASK_RUNTIME:3:0:0", nil
	}
	f.host.stop = func(st *state.Store, k *signing.Key, xml []byte) error {
		if f.fault == "stop" {
			return errors.New("fixture stop")
		}
		if _, err := st.VerifyWindowsTask(k, xml, sid); err != nil {
			return err
		}
		if verifyWindowsTaskXML(f.xml, xml) != nil {
			return errors.New("fixture wrong source")
		}
		f.effects = append(f.effects, "stop")
		f.running = false
		return nil
	}
	f.host.remove = func(n, u string, snapshot []byte) error {
		identity(n, u)
		locked()
		if !bytes.Equal(snapshot, f.xml) || f.running || f.queued {
			t.Fatal("unsafe delete")
		}
		if f.fault == "delete-before" {
			return errors.New("fixture delete")
		}
		f.effects = append(f.effects, "delete")
		f.xml = nil
		if f.fault == "delete-after" {
			return errors.New("fixture uncertain deletion")
		}
		return nil
	}
	f.host.create = func(n, u string, xml []byte) error {
		identity(n, u)
		locked()
		if f.xml != nil {
			t.Fatal("nonexclusive create")
		}
		if _, err := s.VerifyWindowsTask(key, xml, sid); err != nil {
			t.Fatal("local target not applied before create", err)
		}
		if f.fault == "create-before" {
			return errors.New("fixture create")
		}
		f.effects = append(f.effects, "create")
		f.xml = append([]byte{}, xml...)
		if f.fault == "create-after" {
			return errors.New("fixture uncertain creation")
		}
		return nil
	}
	f.host.start = func(n, u string) error {
		identity(n, u)
		if err := s.CheckServiceSwitchPending(); err != nil {
			t.Fatal("start before finish", err)
		}
		writer, err := state.AcquireWriter(s.Dir)
		if err != nil {
			t.Fatal("main writer retained during start", err)
		}
		_ = writer.Release()
		if f.running {
			t.Fatal("repeated start side effect")
		}
		if f.fault == "start-before" {
			return errors.New("fixture start")
		}
		f.effects = append(f.effects, "start")
		f.running = true
		if f.fault == "start-after" {
			return errors.New("fixture uncertain start")
		}
		return nil
	}
	return f
}

func (f *winTaskSwitchFixture) run(id string, out io.Writer) error {
	return switchWindowsTask(f.st, f.host, f.source, f.target, id, out, func() error {
		if f.fault == "release" {
			return errors.New("fixture untrusted release")
		}
		return nil
	}, func() error {
		if f.fault == "health" {
			return errors.New("fixture wrong version")
		}
		return nil
	}, f.check)
}

func winSwitchID(t *testing.T, out *bytes.Buffer) string {
	t.Helper()
	id := regexp.MustCompile(`[0-9a-f]{64}`).FindString(out.String())
	if id == "" {
		t.Fatal("missing recovery identity", out.String())
	}
	return id
}

func TestWinTaskSwitchRecovery(t *testing.T) {
	for _, fault := range []string{"none", "delete-before", "delete-after", "create-before", "create-after", "start-before", "start-after", "health"} {
		t.Run(fault, func(t *testing.T) {
			f := newWinTaskSwitchFixture(t)
			f.fault = fault
			var out bytes.Buffer
			err := f.run("", &out)
			if (fault == "none") != (err == nil) {
				t.Fatal("unexpected first result", err)
			}
			id := winSwitchID(t, &out)
			if err != nil && !strings.Contains(err.Error(), "--recover "+id) {
				t.Fatal("missing recover hint", err)
			}
			f.fault = ""
			if err = f.run(id, io.Discard); err != nil {
				t.Fatal("recovery", err)
			}
			if err = f.st.CheckWindowsTaskSwitchCompleted(f.key, id); err != nil {
				t.Fatal(err)
			}
			if !f.running || !bytes.Equal(f.xml, f.target) {
				t.Fatal("target did not run")
			}
			before := strings.Join(f.effects, ",")
			if err = f.run(id, io.Discard); err != nil {
				t.Fatal("idempotent recovery", err)
			}
			if strings.Join(f.effects, ",") != before {
				t.Fatal("completed recovery repeated side effects")
			}
			for _, effect := range []string{"delete", "create", "start"} {
				n := 0
				for _, actual := range f.effects {
					if actual == effect {
						n++
					}
				}
				if n != 1 {
					t.Fatal("duplicate or absent effect", effect, n)
				}
			}
		})
	}
}

func TestWinTaskSwitchPreflight(t *testing.T) {
	for _, fault := range []string{"presence", "query", "runtime", "release", "absent", "unknown", "queued", "binary", "source-binary", "stop", "writer"} {
		t.Run(fault, func(t *testing.T) {
			f := newWinTaskSwitchFixture(t)
			f.fault = fault
			switch fault {
			case "absent":
				f.xml = nil
			case "unknown":
				f.xml = bytes.Replace(f.source, []byte("LeastPrivilege"), []byte("HighestAvailable"), 1)
			case "queued":
				f.queued = true
			case "binary":
				if err := os.WriteFile(f.newPath, []byte("changed"), 0700); err != nil {
					t.Fatal(err)
				}
			case "source-binary":
				if err := os.WriteFile(f.oldPath, []byte("changed"), 0700); err != nil {
					t.Fatal(err)
				}
			case "writer":
				w, err := state.AcquireWriter(f.st.Dir)
				if err != nil {
					t.Fatal(err)
				}
				defer w.Release()
			}
			before := append([]byte{}, f.xml...)
			if f.run("", io.Discard) == nil {
				t.Fatal("unsafe switch accepted")
			}
			if !bytes.Equal(before, f.xml) {
				t.Fatal("changed external configuration on preflight failure")
			}
			for _, effect := range f.effects {
				if effect != "stop" {
					t.Fatal("destructive effect on preflight failure", effect)
				}
			}
			if err := f.st.CheckServiceSwitchPending(); err != nil {
				t.Fatal("preflight created pending", err)
			}
		})
	}
}

func TestWinTaskSwitchRecoveryRefuse(t *testing.T) {
	for _, fault := range []string{"source-running", "source-queued", "target-running-pending", "unknown", "wrong-user", "wrong-candidate", "local-drift", "lost-pending", "foreign-pending", "unhealthy-complete"} {
		t.Run(fault, func(t *testing.T) {
			f := newWinTaskSwitchFixture(t)
			f.fault = "delete-before"
			var out bytes.Buffer
			if f.run("", &out) == nil {
				t.Fatal("expected interrupted switch")
			}
			id := winSwitchID(t, &out)
			f.fault = ""
			switch fault {
			case "source-running":
				f.running = true
			case "source-queued":
				f.queued = true
			case "target-running-pending":
				f.xml = f.target
				f.running = true
			case "unknown":
				f.xml = []byte("unknown")
			case "wrong-user":
				f.host.sid = "S-1-5-21-101-200-300-1001"
			case "wrong-candidate":
				f.target = bytes.Replace(f.target, []byte("new.exe"), []byte("other.exe"), 1)
			case "local-drift":
				if err := os.WriteFile(filepath.Join(f.st.Dir, "windows-task.json"), []byte("unknown"), 0600); err != nil {
					t.Fatal(err)
				}
			case "lost-pending":
				if err := os.Remove(filepath.Join(f.st.Dir, "service-switch.pending.json")); err != nil {
					t.Fatal(err)
				}
			case "foreign-pending":
				if err := os.WriteFile(filepath.Join(f.st.Dir, "service-switch.pending.json"), []byte("other"), 0600); err != nil {
					t.Fatal(err)
				}
			case "unhealthy-complete":
				if err := f.run(id, io.Discard); err != nil {
					t.Fatal(err)
				}
				f.fault = "health"
			}
			effects := strings.Join(f.effects, ",")
			if f.run(id, io.Discard) == nil {
				t.Fatal("invalid recovery accepted")
			}
			if strings.Join(f.effects, ",") != effects {
				t.Fatal("invalid recovery mutated task")
			}
		})
	}
}

func TestWinTaskSwitchRollback(t *testing.T) {
	f := newWinTaskSwitchFixture(t)
	var out bytes.Buffer
	if err := f.run("", &out); err != nil {
		t.Fatal(err)
	}
	original := winSwitchID(t, &out)
	reverse := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: f.check.bindings.TargetSHA256, TargetSHA256: f.check.bindings.SourceSHA256}, targetPath: f.oldPath}
	ok := func() error { return nil }
	f.fault = "create-after"
	out.Reset()
	if rollbackWindowsTask(f.st, f.host, original, f.source, "", &out, ok, ok, reverse) == nil {
		t.Fatal("expected reverse interruption")
	}
	reverseID := winSwitchID(t, &out)
	f.fault = ""
	if err := rollbackWindowsTask(f.st, f.host, original, f.source, reverseID, io.Discard, ok, ok, reverse); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(f.xml, f.source) || !f.running {
		t.Fatal("rollback did not run original")
	}
	out.Reset()
	if err := f.run("", &out); err != nil {
		t.Fatal("repeat upgrade after rollback", err)
	}
	if winSwitchID(t, &out) == original {
		t.Fatal("new upgrade reused old completion identity")
	}
}
