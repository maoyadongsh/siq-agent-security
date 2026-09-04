package adapterinstall

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func testOpts(t *testing.T, platform string) Options {
	t.Helper()
	home := t.TempDir()
	state := t.TempDir()
	bin := filepath.Join(home, "bin", "agentshield")
	_ = os.MkdirAll(filepath.Dir(bin), 0o755)
	_ = os.WriteFile(bin, []byte("#!/bin/sh\n"), 0o700)
	return Options{
		Platform: platform,
		Home:     home,
		StateDir: state,
		Binary:   bin,
		Endpoint: "http://127.0.0.1:47611",
		Mode:     "block",
		Now:      time.Date(2026, 9, 4, 6, 0, 0, 0, time.UTC),
	}
}

func TestHermesInstallUninstallRoundTrip(t *testing.T) {
	opts := testOpts(t, Hermes)
	res, err := Install(opts)
	if err != nil {
		t.Fatal(err)
	}
	plugin := filepath.Join(opts.Home, ".hermes", "plugins", "agentshield", "plugin.yaml")
	initPy := filepath.Join(opts.Home, ".hermes", "plugins", "agentshield", "__init__.py")
	if !exists(plugin) || !exists(initPy) {
		t.Fatalf("plugin files missing: %+v", res.Paths)
	}
	st, err := Status(opts)
	if err != nil || st.Note != "installed" {
		t.Fatalf("status: %+v %v", st, err)
	}
	if _, err := Uninstall(opts); err != nil {
		t.Fatal(err)
	}
	if exists(plugin) {
		t.Fatal("uninstall must remove the plugin directory it created")
	}
}

func TestOpenClawMergesInstallPolicyAndRestoresBackup(t *testing.T) {
	opts := testOpts(t, OpenClaw)
	oc := filepath.Join(opts.Home, ".openclaw", "openclaw.json")
	_ = os.MkdirAll(filepath.Dir(oc), 0o700)
	_ = os.WriteFile(oc, []byte(`{"gateway":{"mode":"local"},"security":{"extra":true}}`), 0o600)

	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	raw, _ := os.ReadFile(oc)
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if doc["gateway"] == nil {
		t.Fatal("must preserve unrelated keys")
	}
	sec := doc["security"].(map[string]any)
	if sec["extra"] != true {
		t.Fatal("must preserve nested unrelated keys")
	}
	pol := sec["installPolicy"].(map[string]any)
	exec := pol["exec"].(map[string]any)
	if exec["command"] != opts.Binary {
		t.Fatalf("command=%v", exec["command"])
	}

	if _, err := Uninstall(opts); err != nil {
		t.Fatal(err)
	}
	restored, _ := os.ReadFile(oc)
	if !strings.Contains(string(restored), `"extra":true`) || strings.Contains(string(restored), "installPolicy") {
		t.Fatalf("restore did not put the original file back: %s", restored)
	}
}

func TestCodeBuddyIsIdempotentAndFailClosedUninstallWithoutRecord(t *testing.T) {
	opts := testOpts(t, CodeBuddy)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	raw, _ := os.ReadFile(filepath.Join(opts.Home, ".codebuddy", "settings.json"))
	if strings.Count(string(raw), "agentshield hook codebuddy") != 2 { // Pre + Post
		t.Fatalf("expected one command per event, got %s", raw)
	}
	fresh := testOpts(t, CodeBuddy)
	if _, err := Uninstall(fresh); err == nil {
		t.Fatal("uninstall without a record must fail")
	}
}

func TestTraeIsAuditOnly(t *testing.T) {
	opts := testOpts(t, Trae)
	res, err := Install(opts)
	if err != nil || res.Action != "skipped" {
		t.Fatalf("%+v %v", res, err)
	}
}

func TestEmbeddedAssetsMatchRuntimeTree(t *testing.T) {
	root := filepath.Join("..", "..", "..", "..", "adapters", "runtime")
	pairs := [][2]string{
		{"assets/hermes/plugin.yaml", "hermes-agentshield/plugin.yaml"},
		{"assets/hermes/__init__.py", "hermes-agentshield/__init__.py"},
		{"assets/openclaw/package.json", "openclaw-agentshield/package.json"},
		{"assets/openclaw/index.ts", "openclaw-agentshield/index.ts"},
	}
	for _, p := range pairs {
		want, err := os.ReadFile(filepath.Join(root, p[1]))
		if err != nil {
			t.Fatalf("runtime tree missing %s (keep embed in sync): %v", p[1], err)
		}
		got, err := embedded.ReadFile(p[0])
		if err != nil {
			t.Fatal(err)
		}
		if string(got) != string(want) {
			t.Fatalf("embed drifted from adapters/runtime/%s — copy the runtime file into adapterinstall/assets", p[1])
		}
	}
}
