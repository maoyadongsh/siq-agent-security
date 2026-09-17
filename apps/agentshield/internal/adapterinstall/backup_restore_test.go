package adapterinstall

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
)

// reflectJSON compares restored configuration semantically: the host file is
// re-encoded on write, so restoration is judged by content, not byte layout.
func reflectJSON(t *testing.T, raw []byte) map[string]any {
	t.Helper()
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	return doc
}

// Unicode and space in the paths of every configuration the installer may
// touch must survive the full 接入 → 还原 round trip: restored bytes, restored
// modes, user fields kept, and nothing left behind in either config root.
func TestUnicodeAndSpaceConfigPathsRestoreBytesAndModes(t *testing.T) {
	home := filepath.Join(t.TempDir(), "用户 目录")

	// Hermes named profile with a non-ASCII, space-containing name.
	profile := filepath.Join(home, ".hermes", "profiles", "工作 区A")
	cfg := filepath.Join(profile, "config.yaml")
	putTestFile(t, cfg, []byte("model: 工作区\n"), 0600)
	notes := filepath.Join(profile, "notes", "我的笔记.txt")
	putTestFile(t, notes, []byte("keep me\n"), 0600)
	var target hermeshome.Root
	for _, root := range hermeshome.Scan(hermeshome.Options{Home: home, OS: "linux"}).Roots {
		if root.Path == profile {
			target = root
		}
	}
	if target.ID == "" {
		t.Fatal("unicode profile not discovered")
	}
	hopts := WithHermesInstance(testOptsAt(t, home), target)
	if _, err := Install(hopts); err != nil {
		t.Fatal(err)
	}
	if _, err := Uninstall(hopts); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(cfg)
	if err != nil || string(raw) != "model: 工作区\n" {
		t.Fatal("profile config not restored byte-identical", err)
	}
	if info, err := os.Stat(cfg); err != nil || (runtime.GOOS != "windows" && info.Mode().Perm() != 0600) {
		t.Fatal("profile config mode not restored")
	}
	if data, err := os.ReadFile(notes); err != nil || string(data) != "keep me\n" {
		t.Fatal("user file inside the profile was removed")
	}
	// Removal is file-scoped by design: the plan owns files it created, never
	// directory trees, so an emptied product directory may remain.
	if exists(filepath.Join(profile, "plugins", "siq-agent-security", "plugin.yaml")) || exists(hopts.wrapperPath()) {
		t.Fatal("uninstall left product files in the unicode profile")
	}

	// OpenClaw surgical registration over a pre-existing configuration.
	opts := testOptsAt(t, home)
	opts.Platform = OpenClaw
	oc := filepath.Join(home, ".openclaw", "openclaw.json")
	original := `{"gateway":{"mode":"local"},"custom":"保留","security":{"extra":true}}`
	putTestFile(t, oc, []byte(original), 0640)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	if _, err := Uninstall(opts); err != nil {
		t.Fatal(err)
	}
	restored, err := os.ReadFile(oc)
	if err != nil {
		t.Fatal(err)
	}
	if doc := reflectJSON(t, restored); doc["custom"] != "保留" || doc["gateway"].(map[string]any)["mode"] != "local" || doc["security"].(map[string]any)["extra"] != true {
		t.Fatal("user fields lost on restore", doc)
	}
	if _, exists := reflectJSON(t, restored)["security"].(map[string]any)["installPolicy"]; exists {
		t.Fatal("product registration not removed")
	}
	// 0640 was the file's mode before the install touched it; the surgical
	// restore must put that back, not the installer's write mode.
	if info, err := os.Stat(oc); err != nil || (runtime.GOOS != "windows" && info.Mode().Perm() != 0640) {
		t.Fatal("surgical restore lost the original mode")
	}
}

// Uninstalling one instance is a restore of exactly that instance: the
// sibling's configuration bytes, mode, plugin files, and wrapper remain
// byte-for-byte what they were while it stays installed.
func TestUninstallOfOneInstanceRestoresOnlyThatInstance(t *testing.T) {
	opts := testOpts(t, Hermes)
	var profiles [2]hermeshome.Root
	for i, name := range []string{"work-a", "工作 b"} {
		root := filepath.Join(opts.Home, ".hermes", "profiles", name)
		putTestFile(t, filepath.Join(root, "config.yaml"), []byte("model: "+name+"\n"), 0640)
		profiles[i] = hermeshome.Root{ID: "", Path: root}
		for _, scanned := range hermeshome.Scan(hermeshome.Options{Home: opts.Home, OS: "linux"}).Roots {
			if scanned.Path == root {
				profiles[i] = scanned
			}
		}
		if profiles[i].ID == "" {
			t.Fatal("profile not discovered", name)
		}
	}
	first, second := WithHermesInstance(opts, profiles[0]), WithHermesInstance(opts, profiles[1])
	for _, o := range []Options{first, second} {
		if _, err := Install(o); err != nil {
			t.Fatal(err)
		}
		if runtime.GOOS == "windows" {
			if _, err := os.Lstat(o.wrapperPath()); !os.IsNotExist(err) {
				t.Fatalf("Windows install must not create an unsupported shell wrapper: %v", err)
			}
		}
	}
	if _, err := Uninstall(second); err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS == "windows" {
		for _, o := range []Options{first, second} {
			if _, err := os.Lstat(o.wrapperPath()); !os.IsNotExist(err) {
				t.Fatalf("Windows uninstall must leave unsupported shell wrappers absent: %v", err)
			}
		}
	}
	sibling := filepath.Join(opts.Home, ".hermes", "profiles", "work-a")
	raw, err := os.ReadFile(filepath.Join(sibling, "config.yaml"))
	if err != nil || string(raw) != "model: work-a\n" {
		t.Fatal("sibling config changed by other instance's uninstall")
	}
	if info, err := os.Stat(filepath.Join(sibling, "config.yaml")); err != nil || (runtime.GOOS != "windows" && info.Mode().Perm() != 0640) {
		t.Fatal("sibling config mode changed")
	}
	if !exists(filepath.Join(sibling, "plugins", "siq-agent-security", "plugin.yaml")) {
		t.Fatal("sibling plugin removed by other instance's uninstall")
	}
	if runtime.GOOS != "windows" && !exists(first.wrapperPath()) {
		t.Fatal("sibling wrapper removed by other instance's uninstall")
	}
}

// A plan is only valid against the configuration it previewed. Edits that
// land between a prepared uninstall and its apply must be refused on the
// restore path with the same ErrPlanChanged contract as the install path.
func TestUninstallPlanRejectsConfigChangedAfterPrepare(t *testing.T) {
	home := t.TempDir()
	opts := testOptsAt(t, home)
	opts.Platform = OpenClaw
	oc := filepath.Join(home, ".openclaw", "openclaw.json")
	putTestFile(t, oc, []byte(`{"gateway":{"mode":"local"},"user":{"field":1}}`), 0600)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	p := testPlan(t, opts, "uninstall")
	if len(p.payload.Inputs) == 0 {
		t.Fatal("uninstall plan captured no before-images")
	}
	putTestFile(t, oc, []byte(`{"gateway":{"mode":"local"},"user":{"field":2}}`), 0600)
	if _, err := Apply(p); !errors.Is(err, ErrPlanChanged) {
		t.Fatalf("stale uninstall must be refused with ErrPlanChanged, got %v", err)
	}
}

// Moving or removing the instance root between a prepared uninstall and its
// apply invalidates the plan the same way it invalidates an install: the
// path-derived identity no longer matches the pinned instance.
func TestUninstallPlanRejectsMovedInstanceAfterPrepare(t *testing.T) {
	home := t.TempDir()
	profile := filepath.Join(home, ".hermes", "profiles", "工作 区A")
	putTestFile(t, filepath.Join(profile, "config.yaml"), []byte("model: 工作区\n"), 0600)
	var target hermeshome.Root
	for _, root := range hermeshome.Scan(hermeshome.Options{Home: home, OS: "linux"}).Roots {
		if root.Path == profile {
			target = root
		}
	}
	if target.ID == "" {
		t.Fatal("profile not discovered")
	}
	opts := WithHermesInstance(testOptsAt(t, home), target)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	p := testPlan(t, opts, "uninstall")
	if err := os.Rename(profile, profile+"-moved"); err != nil {
		t.Fatal(err)
	}
	if _, err := Apply(p); !errors.Is(err, ErrPlanChanged) {
		t.Fatalf("moved instance must refuse the uninstall plan, got %v", err)
	}
	// The moved instance is untouched: its plugin files traveled with it.
	if !exists(filepath.Join(profile+"-moved", "plugins", "siq-agent-security", "plugin.yaml")) {
		t.Fatal("moved instance lost its plugin files")
	}
}
