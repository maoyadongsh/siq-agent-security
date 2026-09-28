package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strings"
	"sync/atomic"
	"testing"
)

func TestCmdSyncSkipsWithoutCreds(t *testing.T) {
	dir := t.TempDir()
	if _, err := state.Open(dir); err != nil {
		t.Fatal(err)
	}
	t.Setenv("AGENTSHIELD_STATE_DIR", dir)
	t.Setenv("AGENTSHIELD_SIGNING_KEY_SEED", "")
	t.Setenv("SIQ_AS_EDGE_IDENTITY", "")
	t.Setenv("SIQ_AS_EDGE_SECRET", "")
	t.Setenv("SIQ_AS_EDGE_TASK_ID", "")
	isolateSyncHome(t, filepath.Join(dir, "home"))
	_ = os.MkdirAll(filepath.Join(dir, "home"), 0o700)

	if err := cmdSync([]string{"--control-api", "http://127.0.0.1:9"}); err != nil {
		t.Fatalf("missing creds must skip: %v", err)
	}
}

func TestCmdSyncHTTPFailureUnchanged(t *testing.T) {
	dir := t.TempDir()
	if _, err := state.Open(dir); err != nil {
		t.Fatal(err)
	}
	t.Setenv("AGENTSHIELD_STATE_DIR", dir)
	t.Setenv("AGENTSHIELD_SIGNING_KEY_SEED", "")
	// Existing user data requires an established signing identity.
	if _, err := signing.Load(dir); err != nil {
		t.Fatal(err)
	}
	isolateSyncHome(t, filepath.Join(dir, "home"))
	home := filepath.Join(dir, "home")
	_ = os.MkdirAll(filepath.Join(home, ".hermes"), 0o700)
	if err := os.WriteFile(filepath.Join(home, ".hermes", "config.yaml"), []byte("model: x\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	var requests atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.Method != http.MethodPost || r.URL.Path != "/edge/v1/batches" {
			t.Errorf("unexpected sync request: %s %s", r.Method, r.URL.Path)
		}
		w.WriteHeader(401)
	}))
	defer srv.Close()
	secret := filepath.Join(dir, "secret")
	if err := os.WriteFile(secret, []byte("edge-secret\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	err := cmdSync([]string{
		"--control-api", srv.URL,
		"--identity", "edge-as",
		"--secret-file", secret,
		"--task-id", "tsk-1",
	})
	if requests.Load() != 1 {
		t.Fatalf("expected one nonempty inventory batch; got %d requests", requests.Load())
	}
	if err == nil {
		t.Fatal("401 must fail")
	}
	if !strings.Contains(err.Error(), "local decisions unchanged") {
		t.Fatalf("%v", err)
	}
	if strings.Contains(err.Error(), "edge-secret") {
		t.Fatal("secret leaked in error")
	}
	if ents, _ := os.ReadDir(filepath.Join(dir, "grants")); len(ents) != 0 {
		t.Fatalf("sync must not write grants: %v", ents)
	}
	if ents, _ := os.ReadDir(filepath.Join(dir, "admissions")); len(ents) != 0 {
		t.Fatalf("sync must not write admissions: %v", ents)
	}
}

func TestCmdExportWritesFile(t *testing.T) {
	dir := t.TempDir()
	if _, err := state.Open(dir); err != nil {
		t.Fatal(err)
	}
	t.Setenv("AGENTSHIELD_STATE_DIR", dir)
	t.Setenv("AGENTSHIELD_SIGNING_KEY_SEED", "")
	// Existing user data requires an established signing identity.
	if _, err := signing.Load(dir); err != nil {
		t.Fatal(err)
	}
	isolateSyncHome(t, filepath.Join(dir, "home"))
	_ = os.MkdirAll(filepath.Join(dir, "home"), 0o700)
	rawDir := filepath.Join(dir, "raw-task-content", "content")
	if err := os.MkdirAll(rawDir, 0o700); err != nil {
		t.Fatal(err)
	}
	const rawSentinel = "PRIVATE_RAW_CONTENT_MUST_NOT_ENTER_CLI_EXPORT"
	if err := os.WriteFile(filepath.Join(rawDir, "raw-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.json"), []byte(rawSentinel), 0o600); err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(dir, "bundle.json")
	if err := cmdExport([]string{"--out", out}); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(raw, []byte(`"format": "agentshield.export.v1"`)) {
		t.Fatalf("format: %s", raw[:min(200, len(raw))])
	}
	if bytes.Contains(raw, []byte(rawSentinel)) || bytes.Contains(raw, []byte("raw-task-content")) {
		t.Fatal("raw content store must not enter CLI export")
	}
	var doc map[string]any
	if json.Unmarshal(raw, &doc) != nil {
		t.Fatal("json")
	}
	st, err := os.Stat(out)
	if err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" && st.Mode().Perm() != 0o600 {
		t.Fatalf("perm %o", st.Mode().Perm())
	}
}

// Discovery must never depend on this developer's or runner's real home.
func isolateSyncHome(t *testing.T, home string) {
	t.Helper()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("HERMES_HOME", filepath.Join(home, ".hermes"))
	t.Setenv("LOCALAPPDATA", filepath.Join(home, "AppData", "Local"))
	t.Setenv("WORKBUDDY_CONFIG_DIR", filepath.Join(home, ".workbuddy"))
	t.Setenv("SIQ_AS_CONNECTORS_DIR", "")
}
