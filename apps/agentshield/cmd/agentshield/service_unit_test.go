package main

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"runtime"
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
