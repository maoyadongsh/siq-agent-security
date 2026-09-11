package adapterinstall

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
)

func TestNativeYAMLGuardRefusesAliasesAndTags(t *testing.T) {
	for _, raw := range []string{"a: &shared [value]\nb: *shared\n", "a: !!python/object {}\n", "a:\x00b", "x: &0 [a]\ny: *0\n"} {
		if err := safeNativeInput([]byte(raw)); err == nil {
			t.Fatal("unsafe native input accepted")
		}
	}
	if err := safeNativeInput([]byte("model: fixture\nplugins:\n  enabled: [other]\n")); err != nil {
		t.Fatal(err)
	}
}
func TestNativeEnableMissingProgramDoesNotWrite(t *testing.T) {
	o := testOpts(t, Hermes)
	o.NativeEnable = true
	o.NativeCLI = filepath.Join(o.Home, "missing-cli")
	if _, err := Prepare(o, "install"); !errors.Is(err, ErrNativeCLI) {
		t.Fatal("missing native CLI not rejected")
	}
	if exists(filepath.Join(o.Home, ".hermes")) {
		t.Fatal("failed native preview changed real config")
	}
}
func TestHermesNativeCLIStagesEnableAndRestoresOnlyOwnedSettings(t *testing.T) {
	cli := os.Getenv("SIQ_HERMES_NATIVE_CLI")
	if cli == "" {
		t.Skip("set SIQ_HERMES_NATIVE_CLI for installed native CLI verification")
	}
	o := testOpts(t, Hermes)
	root := filepath.Join(o.Home, ".hermes", "profiles", "work")
	cfg := filepath.Join(root, "config.yaml")
	original := []byte("model: fixture-model\ncustom_fixture:\n  retain: true\nplugins:\n  enabled: [other-plugin]\n  disabled: [siq-agent-security]\n")
	putTestFile(t, cfg, original, 0600)
	for _, r := range hermeshome.Scan(hermeshome.Options{Home: o.Home}).Roots {
		if r.Path == root {
			o = WithHermesInstance(o, r)
		}
	}
	o.NativeEnable = true
	o.NativeCLI = cli
	p := testPlan(t, o, "install")
	raw, _ := os.ReadFile(cfg)
	if !bytes.Equal(raw, original) {
		t.Fatal("native preview changed real profile")
	}
	if _, err := Apply(p); err != nil {
		t.Fatal(err)
	}
	record, err := newestInstanceRecord(o)
	if err != nil || record.NativeOriginal == nil {
		t.Fatal("native ownership missing")
	}
	stage, err := newNativeStage(cli)
	if err != nil {
		t.Fatal(err)
	}
	defer stage.close()
	raw, _ = os.ReadFile(cfg)
	doc, err := stage.document(raw)
	if err != nil {
		t.Fatal(err)
	}
	enabled, err := nativeRegistration(doc)
	if err != nil || !enabled.Enabled || enabled.Disabled || enabled.Override == nil || *enabled.Override {
		t.Fatal("host did not enable plugin correctly")
	}
	raw = append(raw, []byte("\nadded_after_install: keep-me\n")...)
	putTestFile(t, cfg, raw, 0600)
	if _, err := Uninstall(o); err != nil {
		t.Fatal(err)
	}
	restored, _ := os.ReadFile(cfg)
	doc, err = stage.document(restored)
	if err != nil {
		t.Fatal(err)
	}
	state, err := nativeRegistration(doc)
	if err != nil || state.Enabled || !state.Disabled || state.Override != nil {
		t.Fatal("native registration not restored")
	}
	if doc["added_after_install"] != "keep-me" || doc["custom_fixture"] == nil || doc["model"] != "fixture-model" {
		t.Fatal("unrelated settings lost")
	}
	if exists(filepath.Join(o.Home, ".hermes", "plugins", "siq-agent-security")) {
		t.Fatal("other profile modified")
	}
}

func TestHermesNativeCLIRejectsInvalidConfigWithoutHostWrites(t *testing.T) {
	cli := os.Getenv("SIQ_HERMES_NATIVE_CLI")
	if cli == "" {
		t.Skip("native CLI opt-in")
	}
	for name, content := range map[string]string{
		"wrong-plugin-list": "plugins:\n  enabled: not-a-list\n",
		"invalid-yaml":      "plugins: [unterminated\n",
		"alias-graph":       "a: &value [b]\nplugins: *value\n",
	} {
		t.Run(name, func(t *testing.T) {
			o := testOpts(t, Hermes)
			o.NativeEnable, o.NativeCLI = true, cli
			cfg := filepath.Join(o.configRoot(), "config.yaml")
			putTestFile(t, cfg, []byte(content), 0600)
			if _, err := Prepare(o, "install"); err == nil {
				t.Fatal("invalid native configuration accepted")
			}
			raw, _ := os.ReadFile(cfg)
			if string(raw) != content || exists(filepath.Join(o.configRoot(), "plugins")) {
				t.Fatal("failed native preview changed host")
			}
		})
	}
}

func TestHermesNativeCLIFreshConfig(t *testing.T) {
	cli := os.Getenv("SIQ_HERMES_NATIVE_CLI")
	if cli == "" {
		t.Skip("native CLI opt-in")
	}
	o := testOpts(t, Hermes)
	o.NativeEnable, o.NativeCLI = true, cli
	p := testPlan(t, o, "install")
	if exists(o.configRoot()) {
		t.Fatal("fresh config preview wrote host files")
	}
	if _, err := Apply(p); err != nil {
		t.Fatal(err)
	}
	if Inspect(o).ConfigurationState != "ready" {
		t.Fatal("fresh native configuration not verified")
	}
}
