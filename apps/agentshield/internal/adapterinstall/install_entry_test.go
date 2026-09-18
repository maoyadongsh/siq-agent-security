package adapterinstall

import (
	"bytes"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

// Default install previews must state the install-entry boundary. Newer
// OpenClaw versions offer an explicitly enabled operator policy, but a
// normal adapter install must not silently activate it.
func TestInstallEntryIsNeverTakenOver(t *testing.T) {
	for _, platform := range []string{Hermes, OpenClaw, CodeBuddy, Trae} {
		t.Run(platform, func(t *testing.T) {
			opts := testOpts(t, platform)
			plan, err := Prepare(opts, "install")
			if err != nil {
				t.Fatal(err)
			}
			view := plan.View()
			found := false
			for _, step := range view.NextSteps {
				found = found || strings.Contains(step, "安装入口未被接管")
			}
			if !found {
				t.Fatalf("install preview must state the install-entry boundary; steps=%v", view.NextSteps)
			}
			if _, err := Apply(plan); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestOpenClawFreshInstallAddsNoInterceptionFields(t *testing.T) {
	opts := testOpts(t, OpenClaw)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	doc, err := readJSONObject(filepath.Join(opts.Home, ".openclaw", "openclaw.json"))
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(doc, map[string]any{"plugins": doc["plugins"]}) {
		t.Fatalf("fresh install must only register the plugin, got top-level keys %v", keysOf(doc))
	}
	if _, err := Uninstall(opts); err != nil {
		t.Fatal(err)
	}
	if doc, err := readJSONObject(filepath.Join(opts.Home, ".openclaw", "openclaw.json")); err != nil {
		t.Fatal(err)
	} else if _, hasSecurity := doc["security"]; hasSecurity {
		t.Fatalf("uninstall must leave no interception configuration, got top-level keys %v", keysOf(doc))
	}
}

func TestCodeBuddyFreshInstallAddsOnlyHooks(t *testing.T) {
	opts := testOpts(t, CodeBuddy)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	doc, err := readJSONObject(filepath.Join(opts.Home, ".codebuddy", "settings.json"))
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(doc, map[string]any{"hooks": doc["hooks"]}) {
		t.Fatalf("CodeBuddy install may only add hooks, got top-level keys %v", keysOf(doc))
	}
}

func TestHermesControlledInstallPathChecksBeforeNativeInstall(t *testing.T) {
	opts := testOpts(t, Hermes)
	if runtime.GOOS == "windows" {
		plan, err := Prepare(opts, "install")
		if err != nil {
			t.Fatal(err)
		}
		view := plan.View()
		steps := strings.Join(view.NextSteps, "\n")
		if view.RuntimeVerified || !strings.Contains(steps, "安装入口未被接管") || !strings.Contains(steps, "Windows 暂无受控安装命令") {
			t.Fatalf("Windows preview must report the unsupported controlled install path: %+v", view)
		}
	}
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	wrapper := opts.wrapperPath()
	if runtime.GOOS == "windows" {
		// Windows has no supported shell wrapper; installed files do not verify
		// native registration, platform compatibility, or actual tool calls.
		if _, err := os.Lstat(wrapper); !os.IsNotExist(err) {
			t.Fatalf("Windows install must not create an unsupported shell wrapper: %v", err)
		}
		d := Inspect(opts)
		if d.ConfigurationState != "needs_verification" || d.RuntimeState != "unverified" {
			t.Fatalf("Windows file installation claimed native verification: %+v", d)
		}
		for _, code := range []string{"host_registration", "platform_compatibility", "runtime_verification"} {
			if checkStatus(d, code) != "unknown" {
				t.Fatalf("Windows %s must remain unknown without native evidence: %+v", code, d)
			}
		}
	} else {
		raw, err := os.ReadFile(wrapper)
		if err != nil {
			t.Fatalf("controlled install command missing: %v", err)
		}
		info, err := os.Stat(wrapper)
		if err != nil || info.Mode().Perm() != 0o700 {
			t.Fatalf("wrapper mode: %v %v", info, err)
		}
		admit := bytes.Index(raw, []byte("admit"))
		native := bytes.Index(raw, []byte("exec hermes skills install"))
		if admit < 0 || native < 0 || admit > native {
			t.Fatal("controlled install path must check the skill before the native installer runs")
		}
	}
	if _, err := os.Stat(filepath.Join(opts.Home, ".hermes", "config.yaml")); !os.IsNotExist(err) {
		t.Fatalf("install must not modify the Hermes profile config without native enable: %v", err)
	}
}

func keysOf(doc map[string]any) []string {
	out := make([]string, 0, len(doc))
	for k := range doc {
		out = append(out, k)
	}
	return out
}
