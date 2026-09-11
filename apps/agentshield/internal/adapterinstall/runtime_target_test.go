package adapterinstall

import (
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
)

func TestRuntimeTargetRequiresExplicitReadyHermesInstance(t *testing.T) {
	for _, platform := range []string{Hermes, OpenClaw, CodeBuddy} {
		o := testOpts(t, platform)
		if _, err := InspectRuntimeTarget(o); err == nil {
			t.Fatal("implicit or unsupported target accepted")
		}
	}
	o := testOpts(t, Hermes)
	root := hermeshome.Scan(hermeshome.Options{Home: o.Home}).Roots[0]
	o = WithHermesInstance(o, root)
	if _, err := InspectRuntimeTarget(o); err == nil {
		t.Fatal("uninstalled target accepted")
	}
	if exists(o.configRoot()) {
		t.Fatal("inspection wrote host configuration")
	}
}

func TestNativeRuntimeTargetPinsConfigurationServiceAndCLI(t *testing.T) {
	cli := os.Getenv("SIQ_HERMES_NATIVE_CLI")
	if cli == "" {
		t.Skip("set SIQ_HERMES_NATIVE_CLI for installed native CLI verification")
	}
	o := testOpts(t, Hermes)
	root := filepath.Join(o.Home, ".hermes", "profiles", "work")
	cfg := filepath.Join(root, "config.yaml")
	putTestFile(t, cfg, []byte("terminal:\n  env: local\n"), 0600)
	for _, r := range hermeshome.Scan(hermeshome.Options{Home: o.Home}).Roots {
		if r.Path == root {
			o = WithHermesInstance(o, r)
		}
	}
	o.NativeCLI, o.NativeEnable = cli, true
	if _, err := Apply(testPlan(t, o, "install")); err != nil {
		t.Fatal(err)
	}
	base, err := InspectRuntimeTarget(o)
	if err != nil || base.InstanceID != o.Instance.ID || base.ProfilePath != root || base.NativeCLI != cli || base.Home != o.Home {
		t.Fatal("installed target not resolved", err)
	}
	// Defaults must be resolved consistently in diagnostics and launch metadata.
	t.Setenv("HOME", o.Home)
	t.Setenv("USERPROFILE", o.Home)
	defaults := o
	defaults.Home = ""
	normalized, err := InspectRuntimeTarget(defaults)
	if err != nil || normalized != base {
		t.Fatal("default home lost from launch target", err)
	}
	replaced := o
	replaced.NativeCLI = filepath.Join(o.Home, "different-cli")
	if _, err := InspectRuntimeTarget(replaced); err == nil {
		t.Fatal("native program substitution accepted")
	}
	raw, err := os.ReadFile(cfg)
	if err != nil {
		t.Fatal(err)
	}
	putTestFile(t, cfg, append(append([]byte{}, raw...), []byte("\n# external fixture edit\n")...), 0600)
	if next, err := InspectRuntimeTarget(o); err == nil && next.Digest == base.Digest {
		t.Fatal("configuration drift invisible")
	}
	putTestFile(t, cfg, raw, 0600)
	program, err := os.ReadFile(o.Binary)
	if err != nil {
		t.Fatal(err)
	}
	putTestFile(t, o.Binary, append(program, []byte("\n# fixture update\n")...), 0700)
	if next, err := InspectRuntimeTarget(o); err == nil && next.Digest == base.Digest {
		t.Fatal("service program drift invisible")
	}
}
