package adapterinstall

import (
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

func TestWorkBuddyCustomConfigLifecycle(t *testing.T) {
	opts := testOpts(t, WorkBuddy)
	dir := filepath.Join(t.TempDir(), "custom config")
	t.Setenv("WORKBUDDY_CONFIG_DIR", dir)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(dir, "settings.json")
	original := []byte(`{"enabledPlugins":{"sheetagent@workbuddy-builtin":true},"sandbox":{"on":true}}`)
	if err := os.WriteFile(target, original, 0o600); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		res, err := Install(opts)
		if err != nil {
			t.Fatal(err)
		}
		if len(res.Paths) != 1 || res.Paths[0] != target {
			t.Fatalf("wrong installation target: %+v", res.Paths)
		}
	}
	if exists(filepath.Join(opts.Home, ".workbuddy")) {
		t.Fatal("default config was touched")
	}
	if !slices.Contains(Detect(opts.Home), WorkBuddy) {
		t.Fatal("custom config not detected")
	}
	status, err := Status(opts)
	if err != nil || status.Note != "installed" {
		t.Fatalf("status: %+v %v", status, err)
	}
	raw, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Count(string(raw), "hook workbuddy") != 2 {
		t.Fatalf("expected one command per event, got %s", raw)
	}
	if !strings.Contains(string(raw), "--state-dir") || !strings.Contains(string(raw), opts.StateDir) {
		t.Fatal("workbuddy hook must pin --state-dir")
	}
	if strings.Contains(string(raw), "hook codebuddy") {
		t.Fatal("workbuddy install wrote a codebuddy hook")
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if doc["enabledPlugins"].(map[string]any)["sheetagent@workbuddy-builtin"] != true || doc["sandbox"].(map[string]any)["on"] != true {
		t.Fatal("unrelated desktop settings removed")
	}
	snapshot, err := os.ReadFile(target + originalSuffix)
	if err != nil || string(snapshot) != string(original) {
		t.Fatal("original backup changed")
	}
	if _, err := Uninstall(opts); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	doc = map[string]any{}
	if err := json.Unmarshal(data, &doc); err != nil {
		t.Fatal(err)
	}
	if _, ok := doc["hooks"]; ok {
		t.Fatalf("product hooks remained: %s", data)
	}
	if doc["enabledPlugins"].(map[string]any)["sheetagent@workbuddy-builtin"] != true {
		t.Fatal("enabledPlugins removed")
	}
	status, err = Status(opts)
	if err != nil || status.Note != "not installed" {
		t.Fatalf("uninstall status: %+v %v", status, err)
	}
}

func TestWorkBuddyReinstallAfterSurgicalUninstall(t *testing.T) {
	opts := testOpts(t, WorkBuddy)
	dir := filepath.Join(t.TempDir(), "custom config")
	t.Setenv("WORKBUDDY_CONFIG_DIR", dir)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(dir, "settings.json")
	original := []byte(`{"enabledPlugins":{"sheetagent@builtin":true},"sandbox":{"mode":"workspace"}}`)
	if err := os.WriteFile(target, original, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	if _, err := Uninstall(opts); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(target)
	if err != nil || string(got) != string(original) {
		t.Fatalf("uninstall must restore orig bytes, got %s", got)
	}
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	status, err := Status(opts)
	if err != nil || status.Note != "installed" {
		t.Fatalf("reinstall status: %+v %v", status, err)
	}
	raw, err := os.ReadFile(target)
	if err != nil || !strings.Contains(string(raw), "hook workbuddy") {
		t.Fatalf("reinstall missing workbuddy hook: %s", raw)
	}
}

func TestWorkBuddyIgnoresCodeBuddyConfigDir(t *testing.T) {
	opts := testOpts(t, WorkBuddy)
	cb := filepath.Join(t.TempDir(), "codebuddy-only")
	if err := os.MkdirAll(cb, 0o700); err != nil {
		t.Fatal(err)
	}
	sentinel := []byte(`{"env":{"FIXTURE":"codebuddy"}}`)
	if err := os.WriteFile(filepath.Join(cb, "settings.json"), sentinel, 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("CODEBUDDY_CONFIG_DIR", cb)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(filepath.Join(cb, "settings.json"))
	if err != nil || string(got) != string(sentinel) {
		t.Fatal("CODEBUDDY_CONFIG_DIR was used as a WorkBuddy root")
	}
	if exists(filepath.Join(cb, "settings.json"+originalSuffix)) {
		t.Fatal("CodeBuddy config was backed up")
	}
	wb := filepath.Join(opts.Home, ".workbuddy", "settings.json")
	raw, err := os.ReadFile(wb)
	if err != nil || !strings.Contains(string(raw), "hook workbuddy") {
		t.Fatal("default WorkBuddy root was not used")
	}
}

func TestWorkBuddyChangedConfigDoesNotUninstallOtherInstance(t *testing.T) {
	opts := testOpts(t, WorkBuddy)
	first := t.TempDir()
	second := t.TempDir()
	t.Setenv("WORKBUDDY_CONFIG_DIR", first)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	original, err := os.ReadFile(filepath.Join(first, "settings.json"))
	if err != nil {
		t.Fatal(err)
	}
	other := filepath.Join(second, "settings.json")
	if err := os.WriteFile(other, original, 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("WORKBUDDY_CONFIG_DIR", second)
	if _, err := Uninstall(opts); err == nil {
		t.Fatal("must reject another instance's record")
	}
	for _, file := range []string{filepath.Join(first, "settings.json"), other} {
		data, err := os.ReadFile(file)
		if err != nil || string(data) != string(original) {
			t.Fatal("uninstall modified another config")
		}
	}
	t.Setenv("WORKBUDDY_CONFIG_DIR", first)
	if _, err := Uninstall(opts); err != nil {
		t.Fatal(err)
	}
}

func TestWorkBuddyInvalidConfigOverrideNeverFallsBack(t *testing.T) {
	for _, kind := range []string{"relative", "symlink", "ancestor-symlink", "file"} {
		t.Run(kind, func(t *testing.T) {
			opts := testOpts(t, WorkBuddy)
			defaultDir := filepath.Join(opts.Home, ".workbuddy")
			if err := os.Mkdir(defaultDir, 0o700); err != nil {
				t.Fatal(err)
			}
			sentinel := filepath.Join(defaultDir, "settings.json")
			original := []byte(`{"enabledPlugins":{"sheetagent@workbuddy-builtin":true}}`)
			if err := os.WriteFile(sentinel, original, 0o600); err != nil {
				t.Fatal(err)
			}
			dir := "relative-config"
			if kind != "relative" {
				dir = filepath.Join(t.TempDir(), "invalid")
				if kind == "file" {
					if err := os.WriteFile(dir, nil, 0o600); err != nil {
						t.Fatal(err)
					}
				} else {
					if err := os.Symlink(t.TempDir(), dir); err != nil {
						t.Skipf("symlink unavailable: %v", err)
					}
					if kind == "ancestor-symlink" {
						dir = filepath.Join(dir, "child")
					}
				}
			}
			t.Setenv("WORKBUDDY_CONFIG_DIR", dir)
			if _, err := Install(opts); err == nil {
				t.Fatal("invalid override installed")
			}
			if _, err := Uninstall(opts); err == nil {
				t.Fatal("invalid override uninstalled")
			}
			if _, err := Status(opts); err == nil {
				t.Fatal("invalid override status accepted")
			}
			if slices.Contains(Detect(opts.Home), WorkBuddy) {
				t.Fatal("invalid override fell back to default")
			}
			data, err := os.ReadFile(sentinel)
			if err != nil || string(data) != string(original) {
				t.Fatal("default config changed")
			}
			if exists(sentinel + originalSuffix) {
				t.Fatal("default config was backed up")
			}
		})
	}
}

func TestWorkBuddyUninstallLeavesCodeBuddyHook(t *testing.T) {
	home := t.TempDir()
	wb := testOptsAt(t, home)
	wb.Platform = WorkBuddy
	cb := testOptsAt(t, home)
	cb.Platform = CodeBuddy
	cb.StateDir = wb.StateDir
	cb.Binary = wb.Binary
	if _, err := Install(cb); err != nil {
		t.Fatal(err)
	}
	if _, err := Install(wb); err != nil {
		t.Fatal(err)
	}
	if _, err := Uninstall(wb); err != nil {
		t.Fatal(err)
	}
	codebuddy, err := os.ReadFile(filepath.Join(home, ".codebuddy", "settings.json"))
	if err != nil || !strings.Contains(string(codebuddy), "hook codebuddy") {
		t.Fatal("codebuddy hook was removed")
	}
	workbuddy, err := os.ReadFile(filepath.Join(home, ".workbuddy", "settings.json"))
	if err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	if err == nil && strings.Contains(string(workbuddy), "hook workbuddy") {
		t.Fatal("workbuddy hook remained")
	}
}
