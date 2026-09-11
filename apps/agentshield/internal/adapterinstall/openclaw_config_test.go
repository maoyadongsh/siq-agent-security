package adapterinstall

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

func TestOpenClawRuntimeRegistrationRoundTrip(t *testing.T) {
	opts := testOpts(t, OpenClaw)
	oc := filepath.Join(opts.Home, ".openclaw", "openclaw.json")
	if err := os.MkdirAll(filepath.Dir(oc), 0o700); err != nil {
		t.Fatal(err)
	}
	original := `{"plugins":{"allow":["other"],"load":{"paths":["/other/plugin"]},"entries":{"other":{"enabled":true}},"slots":{"memory":"other"}}}`
	if err := os.WriteFile(oc, []byte(original), 0o600); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		if _, err := Install(opts); err != nil {
			t.Fatal(err)
		}
	}
	doc, err := readJSONObject(oc)
	if err != nil {
		t.Fatal(err)
	}
	plugins := doc["plugins"].(map[string]any)
	root := filepath.Join(opts.Home, ".openclaw", "plugins", "siq-agent-security")
	if !reflect.DeepEqual(plugins["allow"], []any{"other", "siq-agent-security"}) ||
		!reflect.DeepEqual(plugins["load"].(map[string]any)["paths"], []any{"/other/plugin", root}) {
		t.Fatal("registration must preserve other plugins and not duplicate our entry")
	}
	if plugins["entries"].(map[string]any)["siq-agent-security"].(map[string]any)["enabled"] != true {
		t.Fatal("runtime entry is not enabled")
	}
	manifest, err := readJSONObject(filepath.Join(root, "openclaw.plugin.json"))
	if err != nil || manifest["id"] != "siq-agent-security" || manifest["configSchema"] == nil {
		t.Fatalf("native loader manifest missing or invalid: %v", err)
	}
	if _, err := Uninstall(opts); err != nil {
		t.Fatal(err)
	}
	restored, err := readJSONObject(oc)
	var want map[string]any
	if err != nil || json.Unmarshal([]byte(original), &want) != nil || !reflect.DeepEqual(restored["plugins"], want["plugins"]) {
		t.Fatal("surgical uninstall changed unrelated plugin configuration")
	}
	if exists(filepath.Join(root, "openclaw.plugin.json")) {
		t.Fatal("uninstall left our manifest")
	}
}

func TestOpenClawRuntimeRegistrationRejectsDisabledOrMalformed(t *testing.T) {
	for _, raw := range []string{
		`{"plugins":{"enabled":false}}`, `{"plugins":{"deny":["siq-agent-security"]}}`,
		`{"plugins":[]}`, `{"plugins":{"allow":"other"}}`, `{"plugins":{"load":{"paths":[42]}}}`,
		`{"plugins":{"entries":[]}}`, `{"plugins":{"entries":{"siq-agent-security":false}}}`,
	} {
		t.Run(raw, func(t *testing.T) {
			opts := testOpts(t, OpenClaw)
			oc := filepath.Join(opts.Home, ".openclaw", "openclaw.json")
			if err := os.MkdirAll(filepath.Dir(oc), 0o700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(oc, []byte(raw), 0o600); err != nil {
				t.Fatal(err)
			}
			if _, err := Install(opts); err == nil {
				t.Fatal("invalid/disabled runtime configuration was silently replaced")
			}
			got, err := os.ReadFile(oc)
			if err != nil || string(got) != raw || exists(filepath.Join(filepath.Dir(oc), "plugins", "siq-agent-security", "index.ts")) {
				t.Fatal("rejected install mutated platform files")
			}
		})
	}
}

func TestOpenClawReinstallRefusesCorruptOwnershipRecord(t *testing.T) {
	opts := testOpts(t, OpenClaw)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	oc := filepath.Join(opts.Home, ".openclaw", "openclaw.json")
	before, err := os.ReadFile(oc)
	if err != nil {
		t.Fatal(err)
	}
	record := filepath.Join(opts.StateDir, "adapter-operations", "openclaw.0.json")
	if err := os.WriteFile(record, []byte("{"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Install(opts); err == nil {
		t.Fatal("corrupt record silently discarded")
	}
	after, err := os.ReadFile(oc)
	if err != nil || string(after) != string(before) {
		t.Fatal("rejected reinstall changed runtime configuration")
	}
}

// Opt-in: exercises the files/config actually emitted by Install using the
// installed platform loader. CI without OpenClaw must report this as skipped.
func TestOpenClawInstalledPluginLoadsNatively(t *testing.T) {
	platformRoot, node := os.Getenv("SIQ_OPENCLAW_NATIVE_ROOT"), os.Getenv("SIQ_OPENCLAW_NATIVE_NODE")
	if platformRoot == "" || node == "" {
		t.Skip("set SIQ_OPENCLAW_NATIVE_ROOT and SIQ_OPENCLAW_NATIVE_NODE for real loader validation")
	}
	opts := testOpts(t, OpenClaw)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	workspace := t.TempDir()
	result := filepath.Join(workspace, "result.json")
	specPath := filepath.Join(workspace, "spec.json")
	raw, err := json.Marshal(map[string]any{"openclaw_root": platformRoot, "workspace": workspace,
		"calls": []any{}, "result_path": result})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(specPath, raw, 0o600); err != nil {
		t.Fatal(err)
	}
	worker, err := filepath.Abs(filepath.Join("..", "..", "..", "..", "scripts", "openclaw-native-worker.mjs"))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, node, worker, specPath)
	command.Dir = workspace
	command.Env = []string{"PATH=" + os.Getenv("PATH"), "HOME=" + os.Getenv("HOME"),
		"OPENCLAW_STATE_DIR=" + filepath.Join(opts.Home, ".openclaw"),
		"OPENCLAW_CONFIG_PATH=" + filepath.Join(opts.Home, ".openclaw", "openclaw.json"),
		"OPENCLAW_DISABLE_BUNDLED_PLUGINS=1", "SIQ_AGENT_SECURITY_STATE_DIR=" + opts.StateDir}
	if err := command.Run(); err != nil {
		t.Fatalf("native loader rejected installed assets/config: %v", err)
	}
	if !exists(result) {
		t.Fatal("native loader did not complete")
	}
}
