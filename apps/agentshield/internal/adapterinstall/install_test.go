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
	plugin := filepath.Join(opts.Home, ".hermes", "plugins", "siq-agent-security", "plugin.yaml")
	initPy := filepath.Join(opts.Home, ".hermes", "plugins", "siq-agent-security", "__init__.py")
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
	if err := json.Unmarshal(restored, &doc); err != nil {
		t.Fatal(err)
	}
	sec = doc["security"].(map[string]any)
	if sec["extra"] != true {
		t.Fatal("extra must remain after surgical uninstall")
	}
	if _, ok := sec["installPolicy"]; ok {
		t.Fatal("installPolicy must be stripped")
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
	if strings.Count(string(raw), "hook codebuddy") != 2 { // Pre + Post
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

func TestReinstallKeepsImmutableOriginal(t *testing.T) {
	opts := testOpts(t, OpenClaw)
	oc := filepath.Join(opts.Home, ".openclaw", "openclaw.json")
	_ = os.MkdirAll(filepath.Dir(oc), 0o700)
	original := `{"gateway":{"mode":"local"},"security":{"extra":true}}` + "\n"
	_ = os.WriteFile(oc, []byte(original), 0o600)

	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	origPath := oc + originalSuffix
	firstOrig, err := os.ReadFile(origPath)
	if err != nil {
		t.Fatal(err)
	}
	if string(firstOrig) != original {
		t.Fatalf("first original snapshot wrong: %s", firstOrig)
	}
	// Second install must not overwrite the immutable original even though live file changed.
	opts.Now = opts.Now.Add(time.Minute)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	secondOrig, _ := os.ReadFile(origPath)
	if string(secondOrig) != original {
		t.Fatal("reinstall overwrote immutable original snapshot")
	}
	if _, err := Uninstall(opts); err != nil {
		t.Fatal(err)
	}
	restored, _ := os.ReadFile(oc)
	var doc map[string]any
	if err := json.Unmarshal(restored, &doc); err != nil {
		t.Fatal(err)
	}
	if doc["gateway"] == nil {
		t.Fatal("gateway missing after uninstall")
	}
	sec := doc["security"].(map[string]any)
	if sec["extra"] != true {
		t.Fatal("extra missing after surgical uninstall")
	}
	if _, ok := sec["installPolicy"]; ok {
		t.Fatal("installPolicy still present")
	}
}

func TestSurgicalUninstallKeepsPostInstallUserFields(t *testing.T) {
	opts := testOpts(t, OpenClaw)
	oc := filepath.Join(opts.Home, ".openclaw", "openclaw.json")
	_ = os.MkdirAll(filepath.Dir(oc), 0o700)
	_ = os.WriteFile(oc, []byte(`{"gateway":{"mode":"local"}}`), 0o600)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	raw, _ := os.ReadFile(oc)
	var doc map[string]any
	_ = json.Unmarshal(raw, &doc)
	doc["user_added_after_install"] = true
	out, _ := json.MarshalIndent(doc, "", "  ")
	_ = os.WriteFile(oc, append(out, '\n'), 0o600)

	res, err := Uninstall(opts)
	if err != nil {
		t.Fatal(err)
	}
	if res.Note == "" || !strings.Contains(res.Note, "surgical") {
		t.Fatalf("expected surgical note, got %+v", res)
	}
	restored, _ := os.ReadFile(oc)
	var got map[string]any
	if err := json.Unmarshal(restored, &got); err != nil {
		t.Fatal(err)
	}
	if got["user_added_after_install"] != true {
		t.Fatal("post-install user field must survive uninstall")
	}
	sec, _ := got["security"].(map[string]any)
	if sec != nil {
		if _, ok := sec["installPolicy"]; ok {
			t.Fatalf("installPolicy must be gone; security=%v", sec)
		}
	}
}

func TestCodeBuddySurgicalUninstallKeepsUserSettings(t *testing.T) {
	opts := testOpts(t, CodeBuddy)
	settings := filepath.Join(opts.Home, ".codebuddy", "settings.json")
	_ = os.MkdirAll(filepath.Dir(settings), 0o700)
	_ = os.WriteFile(settings, []byte(`{"theme":"dark"}`), 0o600)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	raw, _ := os.ReadFile(settings)
	var doc map[string]any
	_ = json.Unmarshal(raw, &doc)
	doc["user_pref"] = "keep-me"
	out, _ := json.MarshalIndent(doc, "", "  ")
	_ = os.WriteFile(settings, append(out, '\n'), 0o600)

	if _, err := Uninstall(opts); err != nil {
		t.Fatal(err)
	}
	restored, _ := os.ReadFile(settings)
	var got map[string]any
	if err := json.Unmarshal(restored, &got); err != nil {
		t.Fatal(err)
	}
	if got["user_pref"] != "keep-me" || got["theme"] != "dark" {
		t.Fatalf("user settings lost: %s", restored)
	}
	if strings.Contains(string(restored), "hook codebuddy") {
		t.Fatal("product hooks must be removed")
	}
}

func TestUninstallConflictReturnsRecoveryPlan(t *testing.T) {
	opts := testOpts(t, CodeBuddy)
	settings := filepath.Join(opts.Home, ".codebuddy", "settings.json")
	_ = os.MkdirAll(filepath.Dir(settings), 0o700)
	_ = os.WriteFile(settings, []byte(`{"theme":"dark"}`), 0o600)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	_ = os.WriteFile(settings, []byte("{broken"), 0o600)
	res, err := Uninstall(opts)
	if err == nil {
		t.Fatal("expected conflict")
	}
	if res == nil || res.Recovery == nil || res.Recovery.LivePath != settings {
		t.Fatalf("want recovery plan, got %+v", res)
	}
	raw, _ := os.ReadFile(settings)
	if string(raw) != "{broken" {
		t.Fatal("conflict must not silently overwrite live broken JSON")
	}
	if _, err := os.Stat(settings + originalSuffix); err != nil {
		t.Fatal("original snapshot must remain for manual recovery")
	}
}

func TestBadJSONRefusesRewrite(t *testing.T) {
	opts := testOpts(t, CodeBuddy)
	settings := filepath.Join(opts.Home, ".codebuddy", "settings.json")
	_ = os.MkdirAll(filepath.Dir(settings), 0o700)
	_ = os.WriteFile(settings, []byte("{not-json"), 0o600)
	if _, err := Install(opts); err == nil || !strings.Contains(err.Error(), "invalid JSON") {
		t.Fatalf("want invalid JSON refusal, got %v", err)
	}
	raw, _ := os.ReadFile(settings)
	if string(raw) != "{not-json" {
		t.Fatal("bad JSON must remain untouched")
	}
}

func TestUnknownModeRejected(t *testing.T) {
	opts := testOpts(t, Hermes)
	opts.Mode = "explode"
	if _, err := Install(opts); err == nil || !strings.Contains(err.Error(), "enforcement_mode") {
		t.Fatalf("want mode rejection, got %v", err)
	}
}

func TestSymlinkConfigRefused(t *testing.T) {
	opts := testOpts(t, CodeBuddy)
	dir := filepath.Join(opts.Home, ".codebuddy")
	_ = os.MkdirAll(dir, 0o700)
	real := filepath.Join(opts.Home, "elsewhere.json")
	_ = os.WriteFile(real, []byte(`{"hooks":{}}`), 0o600)
	link := filepath.Join(dir, "settings.json")
	if err := os.Symlink(real, link); err != nil {
		t.Skipf("symlink: %v", err)
	}
	if _, err := Install(opts); err == nil || !strings.Contains(err.Error(), "symlink") {
		t.Fatalf("want symlink refusal, got %v", err)
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
