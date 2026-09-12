package main

import (
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/state"
	"testing"
)

func TestServiceStopConfirmationAndReadback(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "absent")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	if cmdServiceControl("stop", nil, io.Discard) == nil {
		t.Fatal("unconfirmed stop accepted")
	}
	if cmdServiceControl("status", nil, io.Discard) == nil {
		t.Fatal("uninitialized status accepted")
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("created state")
	}
	st := &state.Store{Dir: t.TempDir()}
	props := map[string]string{"ActiveState": "inactive", "MainPID": "0", "Result": "success"}
	if err := serviceStopped(st, props); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"ActiveState", "MainPID", "Result"} {
		old := props[key]
		props[key] = "unexpected"
		if serviceStopped(st, props) == nil {
			t.Fatal("false normal stop")
		}
		props[key] = old
	}
	if err := os.WriteFile(filepath.Join(st.Dir, state.LockFile), []byte("retained"), 0600); err != nil {
		t.Fatal(err)
	}
	if serviceStopped(st, props) == nil {
		t.Fatal("ignored remaining writer")
	}
	if serviceRunning(map[string]string{"ActiveState": "active", "MainPID": "0"}) {
		t.Fatal("missing process accepted")
	}
}
