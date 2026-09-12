package main

import (
	"bytes"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strconv"
	"strings"
	"testing"
)

func TestSetupRequiresConfirmationBeforeStateCreation(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "absent")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	for _, args := range [][]string{nil, {"--port", "1234"}, {"--confirm-setup", "--port", "0"}, {"--confirm-setup", "--port", "65536"}, {"--confirm-setup", "unexpected"}} {
		if err := cmdSetup(args, io.Discard); err == nil {
			t.Fatal("invalid setup accepted")
		}
		if _, err := os.Lstat(dir); !os.IsNotExist(err) {
			t.Fatal("invalid setup created state")
		}
	}
}

func TestNativeSetupAndReuse(t *testing.T) {
	if runtime.GOOS != "linux" || os.Getenv("SIQ_TEST_SETUP_SYSTEMD") != "1" {
		t.Skip("isolated systemd opt-in required")
	}
	binary := os.Getenv("SIQ_TEST_BINARY")
	if binary == "" {
		t.Fatal("test binary required")
	}
	dir := filepath.Join(t.TempDir(), "state")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	ln.Close()
	st := &state.Store{Dir: dir}
	// Cleanup only a verified source unit belonging to this isolated instance.
	defer func() {
		key, err := signing.LoadExisting(dir)
		if err != nil {
			return
		}
		unit, err := renderUserUnit(binary, dir)
		if err != nil {
			t.Error(err)
			return
		}
		record, err := st.VerifyUserService(key, []byte(unit))
		if err != nil {
			t.Error(err)
			return
		}
		path := filepath.Join(dir, record.UnitName)
		props, err := readUserUnit(runUserSystemctl, record.UnitName)
		if err != nil {
			t.Error(err)
			return
		}
		if unitAbsent(props) {
			return
		}
		if err = verifyUserUnit(props, path, true); err != nil {
			t.Error(err)
			return
		}
		if err = setUserLogin(runUserSystemctl, path, record.UnitName, false); err != nil {
			t.Error(err)
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
	run := func(args ...string) (string, error) {
		c := exec.Command(binary, args...)
		var out bytes.Buffer
		c.Stdout = &out
		c.Stderr = &out
		err := c.Run()
		return out.String(), err
	}
	args := []string{"setup", "--confirm-setup", "--runtime", "--port", strconv.Itoa(port)}
	out, err := run(args...)
	if err != nil {
		t.Fatal(out, err)
	}
	if !strings.Contains(out, "http://127.0.0.1:"+strconv.Itoa(port)+"/") {
		t.Fatal("missing actual management URL")
	}
	urlOutput, err := run("ui", "--print")
	if err != nil || strings.TrimSpace(urlOutput) != "http://127.0.0.1:"+strconv.Itoa(port)+"/" {
		t.Fatal("real CLI UI address", urlOutput, err)
	}
	key, err := signing.LoadExisting(dir)
	if err != nil {
		t.Fatal(err)
	}
	unit, err := renderUserUnit(binary, dir)
	if err != nil {
		t.Fatal(err)
	}
	record, props, err := ownedService(st, []byte(unit), runUserSystemctl)
	if err != nil {
		t.Fatal(err)
	}
	pid := props["MainPID"]
	if out, err := run("service-login", "--enable", "--confirm-enable"); err != nil {
		t.Fatal("enable login", out, err)
	}
	if out, err := run("service-status"); err != nil {
		t.Fatal("enabled service status", out, err)
	}

	before, err := os.ReadFile(filepath.Join(dir, "config.json"))
	if err != nil {
		t.Fatal(err)
	}
	out, err = run(args...)
	if err != nil {
		t.Fatal("repeat setup", out, err)
	}
	props, err = readUserUnit(runUserSystemctl, record.UnitName)
	if err != nil || props["MainPID"] != pid {
		t.Fatal("repeat setup restarted daemon", err)
	}
	if _, err = st.VerifyUserService(key, []byte(unit)); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(filepath.Join(dir, "config.json"))
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("repeat setup changed config")
	}
	if out, err := run("service-login", "--disable"); err != nil {
		t.Fatal("disable login", out, err)
	}
	props, err = readUserUnit(runUserSystemctl, record.UnitName)
	if err != nil || props["MainPID"] != pid || props["UnitFileState"] != "linked-runtime" {
		t.Fatal("disable affected running service", err)
	}
	if _, err := run("setup", "--confirm-setup", "--port", strconv.Itoa(port)); err == nil {
		t.Fatal("silently changed runtime registration scope")
	}
	if out, err := run("service-login", "--enable", "--confirm-enable"); err != nil {
		t.Fatal(out, err)
	}
	for i := 0; i < 2; i++ {
		if out, err := run("teardown", "--confirm-teardown"); err != nil {
			t.Fatal("teardown/retry", out, err)
		}
	}
	props, err = readUserUnit(runUserSystemctl, record.UnitName)
	if err != nil || !unitAbsent(props) {
		t.Fatal("teardown left registration", err)
	}
	after, err = os.ReadFile(filepath.Join(dir, "config.json"))
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("teardown changed data")
	}
	if _, err = st.VerifyUserService(key, []byte(unit)); err != nil {
		t.Fatal("teardown lost signed source", err)
	}
	if out, err := run(args...); err != nil {
		t.Fatal("setup after teardown", out, err)
	}
	if out, err := run("teardown", "--confirm-teardown"); err != nil {
		t.Fatal("final teardown", out, err)
	}

}
