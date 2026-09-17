package adapterinstall

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"testing"
)

func TestHermesNativeCLIProfileIsolationAndDrift(t *testing.T) {
	cli := os.Getenv("SIQ_HERMES_NATIVE_CLI")
	if cli == "" {
		t.Skip("installed native CLI opt-in")
	}
	base := testOpts(t, Hermes)
	var targets []Options
	originals := map[string][]byte{}
	for _, name := range []string{"native-a", "鍘熺敓 b"} {
		root := filepath.Join(base.Home, ".hermes", "profiles", name)
		raw := []byte("model: fixture-model\ncustom_fixture: keep\nplugins:\n  enabled: [other-plugin]\n  disabled: [siq-agent-security]\n")
		putTestFile(t, filepath.Join(root, "config.yaml"), raw, 0600)
		originals[root] = raw
	}
	for _, r := range hermeshome.Scan(hermeshome.Options{Home: base.Home}).Roots {
		if _, ok := originals[r.Path]; ok {
			o := WithHermesInstance(base, r)
			o.NativeCLI = cli
			o.NativeEnable = true
			targets = append(targets, o)
		}
	}
	if len(targets) != 2 {
		t.Fatal("two dedicated profiles not discovered")
	}
	snapshot := func(root string) map[string][32]byte {
		t.Helper()
		got := map[string][32]byte{}
		err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
			if err != nil {
				return err
			}
			rel, e := filepath.Rel(root, path)
			if e != nil {
				return e
			}
			if d.IsDir() {
				got[rel+"/"] = [32]byte{}
				return nil
			}
			if !d.Type().IsRegular() {
				return errors.New("unexpected nonregular fixture")
			}
			raw, e := os.ReadFile(path)
			if e != nil {
				return e
			}
			got[rel] = sha256.Sum256(raw)
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
		return got
	}
	for _, o := range targets {
		before := snapshot(o.configRoot())
		plan := testPlan(t, o, "install")
		if !reflect.DeepEqual(before, snapshot(o.configRoot())) {
			t.Fatal("preview modified actual profile")
		}
		if _, err := Apply(plan); err != nil {
			t.Fatal(err)
		}
		record, err := newestInstanceRecord(o)
		if err != nil || record.NativeOriginal == nil {
			t.Fatal("native backup ownership missing")
		}
	}
	first, second := targets[0], targets[1]
	sibling := snapshot(second.configRoot())
	stale := testPlan(t, first, "uninstall")
	cfg := filepath.Join(first.configRoot(), "config.yaml")
	raw, err := os.ReadFile(cfg)
	if err != nil {
		t.Fatal(err)
	}
	putTestFile(t, cfg, append(raw, []byte("\nadded_after_preview: keep-me\n")...), 0600)
	before := snapshot(first.configRoot())
	if _, err := Apply(stale); !errors.Is(err, ErrPlanChanged) {
		t.Fatalf("stale uninstall accepted: %v", err)
	}
	if !reflect.DeepEqual(before, snapshot(first.configRoot())) || !reflect.DeepEqual(sibling, snapshot(second.configRoot())) {
		t.Fatal("stale plan changed a profile")
	}
	if _, err := Uninstall(first); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(sibling, snapshot(second.configRoot())) {
		t.Fatal("other actual native profile modified")
	}
	stage, err := newNativeStage(cli)
	if err != nil {
		t.Fatal(err)
	}
	defer stage.close()
	raw, err = os.ReadFile(cfg)
	if err != nil {
		t.Fatal(err)
	}
	doc, err := stage.document(raw)
	if err != nil {
		t.Fatal(err)
	}
	reg, err := nativeRegistration(doc)
	if err != nil || reg.Enabled || !reg.Disabled || reg.Override != nil {
		t.Fatal("original SIQ registration not restored")
	}
	if doc["added_after_preview"] != "keep-me" || doc["custom_fixture"] != "keep" {
		t.Fatal("user configuration lost")
	}
	plugins, err := nativePlugins(doc)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(asList(plugins["enabled"]), []any{"other-plugin"}) {
		t.Fatal("unrelated enabled plugin lost")
	}
	if exists(filepath.Join(first.configRoot(), "plugins", "siq-agent-security")) {
		t.Fatal("owned plugin not removed")
	}
	if _, err := Uninstall(second); err != nil {
		t.Fatal(err)
	}
	if raw, err := os.ReadFile(filepath.Join(second.configRoot(), "config.yaml")); err != nil || !bytes.Equal(raw, originals[second.configRoot()]) {
		t.Fatal("unchanged second config not exactly restored")
	}
	t.Log("native preview unchanged; stale plan rejected; sibling tree unchanged; both registrations restored")
}
