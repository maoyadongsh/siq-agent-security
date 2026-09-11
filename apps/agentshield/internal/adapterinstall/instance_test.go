package adapterinstall

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
)

func TestHermesInstancesHaveSeparatePlansAndUninstallRecords(t *testing.T) {
	opts := testOpts(t, Hermes)
	root := filepath.Join(opts.Home, ".hermes", "profiles", "work")
	putTestFile(t, filepath.Join(root, "config.yaml"), []byte("model: work\n"), 0600)
	roots := hermeshome.Scan(hermeshome.Options{Home: opts.Home, OS: "linux"}).Roots
	if len(roots) != 2 {
		t.Fatal("named profile not found")
	}
	first, second := WithHermesInstance(opts, roots[0]), WithHermesInstance(opts, roots[1])
	for _, o := range []Options{first, second} {
		p := testPlan(t, o, "install")
		if p.View().SchemaVersion != "local-adapter-plan/v2" || p.View().InstanceID != o.Instance.ID {
			t.Fatal("missing explicit target")
		}
		if _, err := Apply(p); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := Uninstall(second); err != nil {
		t.Fatal(err)
	}
	if !exists(filepath.Join(first.configRoot(), "plugins", "siq-agent-security", "plugin.yaml")) {
		t.Fatal("other instance removed")
	}
	if exists(filepath.Join(second.configRoot(), "plugins", "siq-agent-security", "plugin.yaml")) {
		t.Fatal("selected instance not removed")
	}
	if _, err := Uninstall(first); err != nil {
		t.Fatal(err)
	}
	if exists(filepath.Join(opts.Home, ".local", "bin", "hermes-skills-install")) {
		t.Fatal("instance install changed shared wrapper")
	}
	raw, err := os.ReadFile(filepath.Join(root, "config.yaml"))
	if err != nil || string(raw) != "model: work\n" {
		t.Fatal("files-only installation changed host config")
	}
}

func TestDefaultInstanceUpgradeRestoresLegacyWrapper(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX wrapper")
	}
	opts := testOpts(t, Hermes)
	legacy := opts.wrapperPath()
	putTestFile(t, legacy, []byte("#!/bin/sh\n# original user wrapper\n"), 0755)
	if _, err := Install(opts); err != nil {
		t.Fatal(err)
	}
	root := hermeshome.Scan(hermeshome.Options{Home: opts.Home, OS: "linux"}).Roots[0]
	targeted := WithHermesInstance(opts, root)
	if _, err := Install(targeted); err != nil {
		t.Fatal(err)
	}
	if _, err := Uninstall(targeted); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(legacy)
	info, statErr := os.Stat(legacy)
	if err != nil || statErr != nil || string(raw) != "#!/bin/sh\n# original user wrapper\n" || info.Mode().Perm() != 0755 {
		t.Fatal("legacy user wrapper was not restored")
	}
	if exists(targeted.wrapperPath()) {
		t.Fatal("new instance wrapper not removed")
	}
}
