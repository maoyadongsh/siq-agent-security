package main

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strings"
	"testing"
)

func TestUserUnitQuotingAndNoJournalCredentials(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Linux path rendering")
	}
	unit, err := renderUserUnit(`/opt/siq % space/bin`, `/data/user $HOME %h "quoted"`)
	if err != nil {
		t.Fatal(err)
	}
	for _, required := range []string{`Environment="SIQ_AGENT_SECURITY_STATE_DIR=/data/user $HOME %%h \"quoted\""`, `ExecStart="/opt/siq %% space/bin" serve`, "StandardOutput=null", "StandardError=null", "UMask=0077", "Restart=no"} {
		if !strings.Contains(unit, required) {
			t.Fatalf("missing safe output: %s", required)
		}
	}
	for _, paths := range [][2]string{{"relative", "/state"}, {"/bin", "relative"}, {"/bin/$EXEC", "/state"}, {"/bin\nExecStart=evil", "/state"}, {"/bin", "/state\x00"}, {`/bin/"quoted"`, "/state"}, {`/bin/back\slash`, "/state"}} {
		if _, err := renderUserUnit(paths[0], paths[1]); err == nil {
			t.Fatal("unsafe path accepted")
		}
	}
}

func TestServiceUnitRequiresInitializationAndDoesNotWrite(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("Linux user unit export")
	}
	dir := filepath.Join(t.TempDir(), "state")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	if err := cmdServiceUnit(nil, io.Discard); err == nil {
		t.Fatal("uninitialized state accepted")
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("export created state")
	}
	if err := cmdInitialize(nil, io.Discard); err != nil {
		t.Fatal(err)
	}
	var a, b bytes.Buffer
	if err := cmdServiceUnit(nil, &a); err != nil {
		t.Fatal(err)
	}
	if err := cmdServiceUnit(nil, &b); err != nil {
		t.Fatal(err)
	}
	if a.String() != b.String() {
		t.Fatal("unstable export")
	}
	if _, err := os.Stat(filepath.Join(dir, "token")); !os.IsNotExist(err) {
		t.Fatal("export created credentials")
	}
	if err := os.WriteFile(filepath.Join(dir, "config.json"), []byte("null"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := cmdServiceUnit(nil, io.Discard); err == nil {
		t.Fatal("null configuration accepted")
	}
}

func TestUserUnitInstanceHome(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("Linux HOME")
	}
	dir := t.TempDir()
	home := filepath.Join(dir, "home 中文 %h $literal")
	if err := os.Mkdir(home, 0700); err != nil {
		t.Fatal(err)
	}
	write := func(value string) {
		b, _ := json.Marshal(map[string]any{"linux_service_home": value})
		if err := os.WriteFile(filepath.Join(dir, "config.json"), b, 0600); err != nil {
			t.Fatal(err)
		}
	}
	baseline, err := renderUserUnit("/opt/siq", dir)
	if err != nil {
		t.Fatal(err)
	}
	write(home)
	unit, err := renderUserUnit("/opt/siq", dir)
	if err != nil {
		t.Fatal(err)
	}
	quoted, _ := systemdQuote("HOME=" + home)
	if !strings.Contains(unit, "Environment="+quoted+"\n") {
		t.Fatal("instance HOME missing")
	}
	if os.Getenv("HOME") == home {
		t.Fatal("caller environment mutated")
	}
	link := filepath.Join(dir, "link")
	if err := os.Symlink(home, link); err != nil {
		t.Fatal(err)
	}
	for _, invalid := range []string{"relative", home + "\nEnvironment=EVIL=1", link, filepath.Join(dir, "missing")} {
		write(invalid)
		if _, err := renderUserUnit("/opt/siq", dir); err == nil {
			t.Fatal("invalid HOME accepted")
		}
	}
	write("")
	restored, err := renderUserUnit("/opt/siq", dir)
	if err != nil || restored != baseline {
		t.Fatal("default unit compatibility changed")
	}
}

func TestUserUnitHomeDriftCannotReplaceSignedOwnership(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("Linux HOME")
	}
	dir := t.TempDir()
	st, err := state.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	if _, err = st.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	key, err := signing.FromSeed(make([]byte, 32))
	if err != nil {
		t.Fatal(err)
	}
	unit, err := renderUserUnit("/opt/siq", dir)
	if err != nil {
		t.Fatal(err)
	}
	record, err := st.PrepareUserService(w, key, []byte(unit))
	if err != nil {
		t.Fatal(err)
	}
	cfg, err := st.LoadConfig()
	if err != nil {
		t.Fatal(err)
	}
	cfg.LinuxServiceHome = t.TempDir()
	if err = st.SaveConfig(cfg); err != nil {
		t.Fatal(err)
	}
	changed, err := renderUserUnit("/opt/siq", dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = st.VerifyUserService(key, []byte(changed)); err == nil {
		t.Fatal("HOME drift accepted")
	}
	if _, err = st.PrepareUserService(w, key, []byte(changed)); err == nil {
		t.Fatal("signed unit silently replaced")
	}
	actual, err := os.ReadFile(filepath.Join(dir, record.UnitName))
	if err != nil || string(actual) != unit {
		t.Fatal("original unit changed")
	}
}
