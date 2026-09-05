package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestCmdSyncSkipsWithoutCreds(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("AGENTSHIELD_STATE_DIR", dir)
	t.Setenv("AGENTSHIELD_SIGNING_KEY_SEED", "")
	t.Setenv("SIQ_AS_EDGE_IDENTITY", "")
	t.Setenv("SIQ_AS_EDGE_SECRET", "")
	t.Setenv("SIQ_AS_EDGE_TASK_ID", "")
	t.Setenv("HOME", filepath.Join(dir, "home"))
	_ = os.MkdirAll(filepath.Join(dir, "home"), 0o700)

	if err := cmdSync([]string{"--control-api", "http://127.0.0.1:9"}); err != nil {
		t.Fatalf("missing creds must skip: %v", err)
	}
}

func TestCmdSyncHTTPFailureUnchanged(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("AGENTSHIELD_STATE_DIR", dir)
	t.Setenv("AGENTSHIELD_SIGNING_KEY_SEED", "")
	t.Setenv("HOME", filepath.Join(dir, "home"))
	home := filepath.Join(dir, "home")
	_ = os.MkdirAll(filepath.Join(home, ".hermes"), 0o700)
	if err := os.WriteFile(filepath.Join(home, ".hermes", "config.yaml"), []byte("model: x\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
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
	t.Setenv("AGENTSHIELD_STATE_DIR", dir)
	t.Setenv("AGENTSHIELD_SIGNING_KEY_SEED", "")
	t.Setenv("HOME", filepath.Join(dir, "home"))
	_ = os.MkdirAll(filepath.Join(dir, "home"), 0o700)
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
