package adapterinstall

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func checkStatus(d Diagnosis, code string) string {
	for _, check := range d.Checks {
		if check.Code == code {
			return check.Status
		}
	}
	return ""
}

func TestDiagnosisSeparatesFilesFromRuntime(t *testing.T) {
	for _, platform := range []string{Hermes, OpenClaw, CodeBuddy} {
		t.Run(platform, func(t *testing.T) {
			opts := testOpts(t, platform)
			if Inspect(opts).ConfigurationState != "not_installed" {
				t.Fatal("fresh installation misidentified")
			}
			if _, err := Install(opts); err != nil {
				t.Fatal(err)
			}
			d := Inspect(opts)
			want := "needs_verification"
			if platform == OpenClaw {
				want = "ready"
			}
			if d.ConfigurationState != want || d.RuntimeState != "unverified" || checkStatus(d, "runtime_verification") != "unknown" {
				t.Fatalf("configuration claimed runtime verification: %+v", d)
			}
		})
	}
}

func TestOpenClawDiagnosisDetectsConfigAndFileDrift(t *testing.T) {
	for _, change := range []string{"disabled", "null_enabled", "denied", "allow_missing", "load_missing", "entry_disabled", "other_endpoint", "other_state", "other_mode", "changed_plugin"} {
		t.Run(change, func(t *testing.T) {
			opts := testOpts(t, OpenClaw)
			if _, err := Install(opts); err != nil {
				t.Fatal(err)
			}
			root := configDir(opts.Home, OpenClaw)
			path := filepath.Join(root, "openclaw.json")
			doc, err := inspectJSON(opts.Home, path)
			if err != nil {
				t.Fatal(err)
			}
			plugins := doc["plugins"].(map[string]any)
			switch change {
			case "disabled":
				plugins["enabled"] = false
			case "null_enabled":
				plugins["enabled"] = nil
			case "denied":
				plugins["deny"] = []any{"siq-agent-security"}
			case "allow_missing":
				plugins["allow"] = []any{"another"}
			case "load_missing":
				plugins["load"] = map[string]any{"paths": []any{}}
			case "entry_disabled":
				plugins["entries"].(map[string]any)["siq-agent-security"] = map[string]any{"enabled": false}
			case "other_endpoint", "other_state", "other_mode":
				path = filepath.Join(root, "siq-agent-security.json")
				doc, err = inspectJSON(opts.Home, path)
				if err != nil {
					t.Fatal(err)
				}
				field := map[string]string{"other_endpoint": "endpoint", "other_state": "tokenPath", "other_mode": "enforcementMode"}[change]
				doc[field] = "unexpected"
			case "changed_plugin":
				path = filepath.Join(root, "plugins", "siq-agent-security", "index.ts")
			}
			raw, _ := json.Marshal(doc)
			if err := os.WriteFile(path, raw, 0o600); err != nil {
				t.Fatal(err)
			}
			before := string(raw)
			d := Inspect(opts)
			if d.ConfigurationState != "incomplete" || d.RuntimeState != "unverified" {
				t.Fatalf("drift hidden: %+v", d)
			}
			after, _ := os.ReadFile(path)
			if before != string(after) {
				t.Fatal("read-only diagnostic mutated configuration")
			}
		})
	}
}

func TestDiagnosticsRejectUnsafeFilesWithoutLeakingContents(t *testing.T) {
	opts := testOpts(t, Hermes)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(opts.Home, ".hermes", "plugins", "siq-agent-security", "config.json")
	for _, size := range []int{1 << 20, (1 << 20) + 1} {
		if err := os.WriteFile(path, []byte(strings.Repeat("x", size)), 0o600); err != nil {
			t.Fatal(err)
		}
		_, err := inspectRead(opts.Home, path)
		if (err != nil) != (size > 1<<20) {
			t.Fatal("file read bound incorrect")
		}
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(path, 0o700); err != nil {
		t.Fatal(err)
	}
	if checkStatus(Inspect(opts), "service_configuration") != "fail" {
		t.Fatal("directory accepted as configuration")
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	external := filepath.Join(t.TempDir(), "private.json")
	if err := os.WriteFile(external, []byte(`{"secret":"must-never-appear"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(external, path); err != nil {
		t.Skip("symlink creation unavailable")
	}
	d := Inspect(opts)
	raw, _ := json.Marshal(d)
	if checkStatus(d, "service_configuration") != "fail" || strings.Contains(string(raw), "must-never-appear") || strings.Contains(string(raw), external) {
		t.Fatal("unsafe config accepted or leaked")
	}
}

func TestCodeBuddyDiagnosticRejectsTextOutsideHooks(t *testing.T) {
	opts := testOpts(t, CodeBuddy)
	path := filepath.Join(configDir(opts.Home, CodeBuddy), "settings.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(map[string]any{"description": opts.Binary + " hook codebuddy"})
	if err := os.WriteFile(path, raw, 0o600); err != nil {
		t.Fatal(err)
	}
	if d := Inspect(opts); checkStatus(d, "host_registration") != "fail" || d.ConfigurationState != "incomplete" {
		t.Fatal("unrelated string accepted as installed hooks")
	}
}
