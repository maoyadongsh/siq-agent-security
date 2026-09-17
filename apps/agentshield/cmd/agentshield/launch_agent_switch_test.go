package main

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strings"
	"testing"
)

// fakeLaunchd models the launchd observations the switch relies on: which
// plist content the loaded job was bootstrapped with, its PID and exit code.
type fakeLaunchd struct {
	t         *testing.T
	label     string
	source    string
	rendered  map[string]string // side name -> rendered plist
	file      string            // state plist path; content decides bootstrap side
	loaded    string            // "" when not loaded, otherwise side name
	pid       int64
	lastExit  string
	mutations []string
	failStart int // number of kickstarts that leave the job exited with code 1
	onStart   func()
}

func (f *fakeLaunchd) control(args ...string) (string, error) {
	joined := strings.Join(args, " ")
	switch {
	case joined == "manageruid":
		return "501", nil
	case joined == "managername":
		return "Aqua", nil
	case joined == "list":
		if f.loaded == "" {
			return "PID\tStatus\tLabel\n", nil
		}
		pid := "-"
		if f.pid > 0 {
			pid = fmt.Sprint(f.pid)
		}
		return "PID\tStatus\tLabel\n" + pid + "\t0\t" + f.label + "\n", nil
	case joined == "print "+launchPrintTarget(501, f.label):
		if f.loaded == "" {
			return "", errors.New("launch-agent: launchctl command failed or timed out; state is unconfirmed")
		}
		return mustLaunchPrint(f.t, f.rendered[f.loaded], f.source, f.pid, f.lastExit, ""), nil
	case joined == "stop "+f.label:
		f.mutations = append(f.mutations, "stop")
		if f.pid > 0 {
			f.pid, f.lastExit = 0, "0"
		}
		return "", nil
	case joined == "bootout gui/501/"+f.label:
		f.mutations = append(f.mutations, "bootout")
		f.loaded, f.pid, f.lastExit = "", 0, ""
		return "", nil
	case strings.HasPrefix(joined, "bootstrap gui/501 "):
		f.mutations = append(f.mutations, "bootstrap")
		link := strings.TrimPrefix(joined, "bootstrap gui/501 ")
		target, err := os.Readlink(link)
		if err != nil || target != f.source {
			f.t.Fatal("bootstrap of unexpected link", link, err)
		}
		content, err := os.ReadFile(f.file)
		if err != nil {
			f.t.Fatal(err)
		}
		for side, rendered := range f.rendered {
			if rendered == string(content) {
				f.loaded = side
			}
		}
		if f.loaded == "" {
			f.t.Fatal("bootstrapped plist matches no known side")
		}
		f.pid, f.lastExit = 0, "(never exited)"
		return "", nil
	case joined == "kickstart gui/501/"+f.label:
		f.mutations = append(f.mutations, "kickstart")
		lock, err := state.AcquireWriter(filepath.Dir(f.file))
		if err != nil {
			f.t.Fatal("start blocked by caller writer", err)
		}
		_ = lock.Release()
		if f.failStart > 0 {
			f.failStart--
			f.pid, f.lastExit = 0, "1"
			return "", nil
		}
		f.pid, f.lastExit = 4242, "(never exited)"
		if f.onStart != nil {
			f.onStart()
		}
		return "", nil
	}
	f.t.Fatal("unexpected launchctl command", args)
	return "", nil
}

type launchSwitchFixture struct {
	st                 *state.Store
	key                *signing.Key
	home               string
	source, target     []byte
	oldBin, newBin     string
	bindings           state.ServiceBinaryBindings
	launchd            *fakeLaunchd
	sourceFile, record string
}

func newLaunchSwitchFixture(t *testing.T) *launchSwitchFixture {
	t.Helper()
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	instance, err := st.Initialize(w, 0)
	if err != nil {
		t.Fatal(err)
	}
	key, err := signing.Load(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	binDir := t.TempDir()
	oldBin, newBin := filepath.Join(binDir, "old"), filepath.Join(binDir, "new")
	if err = os.WriteFile(oldBin, []byte("old program"), 0700); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(newBin, []byte("new program"), 0700); err != nil {
		t.Fatal(err)
	}
	source, err := renderLaunchAgent(oldBin, st.Dir, instance.InstanceID)
	if err != nil {
		t.Fatal(err)
	}
	target, err := renderLaunchAgent(newBin, st.Dir, instance.InstanceID)
	if err != nil {
		t.Fatal(err)
	}
	record, err := st.PrepareLaunchAgent(w, key, []byte(source))
	if err != nil {
		t.Fatal(err)
	}
	if err = w.Release(); err != nil {
		t.Fatal(err)
	}
	home := t.TempDir()
	sourceFile := mustResolve(t, filepath.Join(st.Dir, record.Label+".plist"))
	if _, err = publishLaunchRegistration(home, sourceFile, record.Label); err != nil {
		t.Fatal(err)
	}
	oldSum, newSum := sha256.Sum256([]byte("old program")), sha256.Sum256([]byte("new program"))
	launchd := &fakeLaunchd{t: t, label: record.Label, source: sourceFile, file: filepath.Join(st.Dir, record.Label+".plist"), rendered: map[string]string{"source": source, "target": target}, loaded: "source", pid: 100, lastExit: "(never exited)"}
	return &launchSwitchFixture{st: st, key: key, home: home, source: []byte(source), target: []byte(target), oldBin: oldBin, newBin: newBin, bindings: state.ServiceBinaryBindings{SourceSHA256: fmt.Sprintf("%x", oldSum), TargetSHA256: fmt.Sprintf("%x", newSum)}, launchd: launchd, sourceFile: sourceFile, record: record.Label}
}

func (f *launchSwitchFixture) host() launchAgentSwitchHost {
	return launchAgentSwitchHost{home: f.home, uid: 501, control: f.launchd.control}
}
func (f *launchSwitchFixture) check() *serviceBinaryCheck {
	return &serviceBinaryCheck{bindings: f.bindings, sourcePath: f.oldBin, targetPath: f.newBin}
}
func ok() error { return nil }

func switchID(t *testing.T, output string) string {
	t.Helper()
	for _, line := range strings.Split(output, "\n") {
		if strings.HasPrefix(line, "切换事务：") {
			id := strings.TrimPrefix(line, "切换事务：")
			if len(id) != 64 {
				t.Fatal("invalid transaction id", id)
			}
			return id
		}
	}
	t.Fatal("no transaction id in output", output)
	return ""
}

func TestSwitchLaunchAgentUpgradeThenRollback(t *testing.T) {
	f := newLaunchSwitchFixture(t)
	config, _ := os.ReadFile(filepath.Join(f.st.Dir, "config.json"))
	var out bytes.Buffer
	ready := func() error {
		if f.launchd.loaded != "target" || f.launchd.pid == 0 {
			return errors.New("not ready")
		}
		return nil
	}
	if err := switchLaunchAgent(f.st, f.host(), f.source, f.target, "", &out, ok, ready, false, f.check()); err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(f.launchd.mutations, ","); got != "stop,bootout,bootstrap,kickstart" {
		t.Fatal("unexpected launchd sequence", got)
	}
	if _, err := f.st.VerifyLaunchAgent(f.key, f.target); err != nil {
		t.Fatal("target ownership not published", err)
	}
	if _, err := f.st.VerifyLaunchAgent(f.key, f.source); err == nil {
		t.Fatal("source still verifies after switch")
	}
	after, _ := os.ReadFile(filepath.Join(f.st.Dir, "config.json"))
	if !bytes.Equal(config, after) {
		t.Fatal("config changed by switch")
	}
	if err := f.st.CheckServiceSwitchPending(); err != nil {
		t.Fatal(err)
	}
	id := switchID(t, out.String())
	// Recovery of a completed, healthy upgrade is read-only reuse.
	before := len(f.launchd.mutations)
	if err := switchLaunchAgent(f.st, f.host(), f.source, f.target, id, io.Discard, ok, ready, false, &serviceBinaryCheck{bindings: f.bindings, targetPath: f.newBin}); err != nil {
		t.Fatal("healthy recovery", err)
	}
	if len(f.launchd.mutations) != before {
		t.Fatal("healthy recovery mutated launchd")
	}
	// Rollback: bindings swapped, back to the recorded source plist.
	rollbackReady := func() error {
		if f.launchd.loaded != "source" || f.launchd.pid == 0 {
			return errors.New("not ready")
		}
		return nil
	}
	back := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: f.bindings.TargetSHA256, TargetSHA256: f.bindings.SourceSHA256}, targetPath: f.oldBin}
	if err := rollbackLaunchAgent(f.st, f.host(), id, []byte("other"), "", io.Discard, ok, rollbackReady, back); err == nil {
		t.Fatal("rollback to unrelated configuration accepted")
	}
	if err := rollbackLaunchAgent(f.st, f.host(), id, f.source, "", io.Discard, ok, rollbackReady, f.check()); err == nil {
		t.Fatal("rollback with un-swapped bindings accepted")
	}
	if err := rollbackLaunchAgent(f.st, f.host(), id, f.source, "", io.Discard, ok, rollbackReady, back); err != nil {
		t.Fatal(err)
	}
	if _, err := f.st.VerifyLaunchAgent(f.key, f.source); err != nil {
		t.Fatal("source not restored", err)
	}
	if f.launchd.loaded != "source" || f.launchd.pid == 0 {
		t.Fatal("rolled back job not running source")
	}
}

func TestSwitchLaunchAgentFailedStartRecovers(t *testing.T) {
	f := newLaunchSwitchFixture(t)
	f.launchd.failStart = 1
	ready := func() error {
		if f.launchd.loaded != "target" || f.launchd.pid == 0 {
			return errors.New("not ready")
		}
		return nil
	}
	var out bytes.Buffer
	err := switchLaunchAgent(f.st, f.host(), f.source, f.target, "", &out, ok, ready, false, f.check())
	if err == nil {
		t.Fatal("failed start reported as success")
	}
	id := switchID(t, out.String())
	if !strings.Contains(err.Error(), "--recover "+id) {
		t.Fatal("failure lost recovery id", err)
	}
	// Files are already switched; launchd holds the target but the job exited.
	if _, err := f.st.VerifyLaunchAgent(f.key, f.target); err != nil {
		t.Fatal(err)
	}
	if f.st.CheckServiceSwitchPending() != nil {
		t.Fatal("pending left behind after applied switch")
	}
	wrong := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: f.bindings.TargetSHA256, TargetSHA256: f.bindings.SourceSHA256}, targetPath: f.newBin}
	if err := switchLaunchAgent(f.st, f.host(), f.source, f.target, id, io.Discard, ok, ready, false, wrong); err == nil {
		t.Fatal("recovery with mismatched bindings accepted")
	}
	if err := switchLaunchAgent(f.st, f.host(), f.source, []byte("other"), id, io.Discard, ok, ready, false, f.check()); err == nil {
		t.Fatal("recovery with replaced target accepted")
	}
	mutationsBefore := len(f.launchd.mutations)
	if err := switchLaunchAgent(f.st, f.host(), f.source, f.target, id, io.Discard, ok, ready, false, &serviceBinaryCheck{bindings: f.bindings, targetPath: f.newBin}); err != nil {
		t.Fatal("recovery", err)
	}
	if got := strings.Join(f.launchd.mutations[mutationsBefore:], ","); got != "bootout,bootstrap,kickstart" {
		t.Fatal("unexpected recovery sequence", got)
	}
	if f.launchd.loaded != "target" || f.launchd.pid == 0 {
		t.Fatal("recovered job not running target")
	}
}

func TestSwitchLaunchAgentRefusesWithoutMutation(t *testing.T) {
	ready := ok
	t.Run("unregistered", func(t *testing.T) {
		f := newLaunchSwitchFixture(t)
		if err := os.Remove(filepath.Join(f.home, "Library", "LaunchAgents", f.record+".plist")); err != nil {
			t.Fatal(err)
		}
		if err := switchLaunchAgent(f.st, f.host(), f.source, f.target, "", io.Discard, ok, ready, false, f.check()); err == nil || len(f.launchd.mutations) != 0 {
			t.Fatal("unregistered agent switched", err)
		}
	})
	t.Run("foreign loaded configuration", func(t *testing.T) {
		f := newLaunchSwitchFixture(t)
		other, _ := renderLaunchAgent("/other/program", f.st.Dir, strings.TrimPrefix(f.record, "dev.siq.agent-security."))
		f.launchd.rendered["source"] = other
		if err := switchLaunchAgent(f.st, f.host(), f.source, f.target, "", io.Discard, ok, ready, false, f.check()); err == nil || len(f.launchd.mutations) != 0 {
			t.Fatal("foreign job stopped", err)
		}
	})
	t.Run("binary drift", func(t *testing.T) {
		f := newLaunchSwitchFixture(t)
		if err := os.WriteFile(f.newBin, []byte("tampered"), 0700); err != nil {
			t.Fatal(err)
		}
		if err := switchLaunchAgent(f.st, f.host(), f.source, f.target, "", io.Discard, ok, ready, false, f.check()); err == nil || len(f.launchd.mutations) != 0 {
			t.Fatal("drifted candidate switched", err)
		}
	})
	t.Run("recheck failure", func(t *testing.T) {
		f := newLaunchSwitchFixture(t)
		bad := func() error { return errors.New("issuer rejected") }
		if err := switchLaunchAgent(f.st, f.host(), f.source, f.target, "", io.Discard, bad, ready, false, f.check()); err == nil || len(f.launchd.mutations) != 0 {
			t.Fatal("rejected candidate interrupted source", err)
		}
		if f.launchd.pid != 100 {
			t.Fatal("source process interrupted")
		}
	})
	t.Run("no bindings", func(t *testing.T) {
		f := newLaunchSwitchFixture(t)
		if err := switchLaunchAgent(f.st, f.host(), f.source, f.target, "", io.Discard, ok, ready, false, nil); err == nil {
			t.Fatal("switch without binary identity accepted")
		}
	})
	t.Run("pending blocks load", func(t *testing.T) {
		f := newLaunchSwitchFixture(t)
		w, err := state.AcquireWriter(f.st.Dir)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = f.st.PrepareLaunchAgentSwitch(w, f.key, f.source, f.target, f.bindings); err != nil {
			t.Fatal(err)
		}
		w.Release()
		f.launchd.loaded, f.launchd.pid = "", 0
		if err := loadRegisteredLaunchAgent(f.st, f.key, f.source, f.home, 501, f.launchd.control); err == nil || len(f.launchd.mutations) != 0 {
			t.Fatal("pending switch bootstrapped", err)
		}
		if err := switchLaunchAgent(f.st, f.host(), f.source, f.target, "", io.Discard, ok, ready, false, f.check()); err == nil {
			t.Fatal("second switch prepared over pending")
		}
	})
	t.Run("running source refuses recovery", func(t *testing.T) {
		f := newLaunchSwitchFixture(t)
		w, err := state.AcquireWriter(f.st.Dir)
		if err != nil {
			t.Fatal(err)
		}
		id, err := f.st.PrepareLaunchAgentSwitch(w, f.key, f.source, f.target, f.bindings)
		w.Release()
		if err != nil {
			t.Fatal(err)
		}
		if err := switchLaunchAgent(f.st, f.host(), f.source, f.target, id, io.Discard, ok, ready, false, &serviceBinaryCheck{bindings: f.bindings, targetPath: f.newBin}); err == nil || len(f.launchd.mutations) != 0 {
			t.Fatal("recovery stopped a running source", err)
		}
	})
}

func TestServiceUpgradeCommandGuards(t *testing.T) {
	for _, args := range [][]string{nil, {"--manifest", "m", "--binary", "b"}, {"--confirm-upgrade"}, {"--manifest", "m", "--binary", "b", "--confirm-upgrade", "extra"}} {
		if err := cmdServiceUpgrade(args, io.Discard); err == nil {
			t.Fatal("confirmation bypass", args)
		}
	}
	for _, args := range [][]string{nil, {"--transaction", strings.Repeat("0", 64), "--binary", "b"}, {"--transaction", strings.Repeat("0", 64), "--binary", "b", "--confirm-rollback", "extra"}} {
		if err := cmdServiceRollback(args, io.Discard); err == nil {
			t.Fatal("confirmation bypass", args)
		}
	}
}
