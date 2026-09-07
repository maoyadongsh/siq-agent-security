package adapterinstall

import (
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"testing"
)

func TestCodeBuddyCustomConfigLifecycle(t *testing.T) {
	opts := testOpts(t, CodeBuddy)
	dir := filepath.Join(t.TempDir(), "custom config")
	t.Setenv("CODEBUDDY_CONFIG_DIR", dir)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(dir, "settings.json")
	original := []byte(`{"env":{"FIXTURE":"preserve"}}`)
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
	if exists(filepath.Join(opts.Home, ".codebuddy")) {
		t.Fatal("default config was touched")
	}
	if !slices.Contains(Detect(opts.Home), CodeBuddy) {
		t.Fatal("custom config not detected")
	}
	status, err := Status(opts)
	if err != nil || status.Note != "installed" {
		t.Fatalf("status: %+v %v", status, err)
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
	var doc map[string]any
	if err := json.Unmarshal(data, &doc); err != nil {
		t.Fatal(err)
	}
	if doc["env"].(map[string]any)["FIXTURE"] != "preserve" {
		t.Fatal("unrelated setting removed")
	}
	status, err = Status(opts)
	if err != nil || status.Note != "not installed" {
		t.Fatalf("uninstall status: %+v %v", status, err)
	}
}

func TestCodeBuddyChangedConfigDoesNotUninstallOtherInstance(t *testing.T) {
	opts := testOpts(t, CodeBuddy)
	first := t.TempDir()
	second := t.TempDir()
	t.Setenv("CODEBUDDY_CONFIG_DIR", first)
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
	t.Setenv("CODEBUDDY_CONFIG_DIR", second)
	if _, err := Uninstall(opts); err == nil {
		t.Fatal("must reject another instance's record")
	}
	for _, file := range []string{filepath.Join(first, "settings.json"), other} {
		data, err := os.ReadFile(file)
		if err != nil || string(data) != string(original) {
			t.Fatal("uninstall modified another config")
		}
	}
	t.Setenv("CODEBUDDY_CONFIG_DIR", first)
	if _, err := Uninstall(opts); err != nil {
		t.Fatal(err)
	}
}

func TestCodeBuddyInvalidConfigOverrideNeverFallsBack(t *testing.T) {
	for _, kind := range []string{"relative", "symlink", "ancestor-symlink", "file"} {
		t.Run(kind, func(t *testing.T) {
			opts := testOpts(t, CodeBuddy)
			defaultDir := filepath.Join(opts.Home, ".codebuddy")
			if err := os.Mkdir(defaultDir, 0o700); err != nil {
				t.Fatal(err)
			}
			sentinel := filepath.Join(defaultDir, "settings.json")
			original := []byte(`{"env":{"FIXTURE":"unchanged"}}`)
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
			t.Setenv("CODEBUDDY_CONFIG_DIR", dir)
			if _, err := Install(opts); err == nil {
				t.Fatal("invalid override installed")
			}
			if _, err := Uninstall(opts); err == nil {
				t.Fatal("invalid override uninstalled")
			}
			if _, err := Status(opts); err == nil {
				t.Fatal("invalid override status accepted")
			}
			if slices.Contains(Detect(opts.Home), CodeBuddy) {
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
