package adapterinstall

import (
	"path/filepath"
	"testing"
)

func TestWorkBuddyLegacyInstancePlanKeepsV1(t *testing.T) {
	o := testOpts(t, WorkBuddy)
	root := configDir(o.Home, WorkBuddy)
	putTestFile(t, filepath.Join(root, "settings.json"), []byte(`{"enabledPlugins":{"builtin":true}}`), 0600)
	o = WithWorkBuddyInstance(o, root)
	p, err := Prepare(o, "install")
	if err != nil {
		t.Fatal(err)
	}
	view := p.View()
	if view.SchemaVersion != "local-adapter-plan/v1" || view.InstanceID != "" || view.InstanceName != "" || view.NativeEnable != nil || view.RuntimeIdentityID != "" {
		t.Fatalf("legacy WorkBuddy was promoted to a managed/Hermes protocol: %+v", view)
	}
	if p.payload.Record.InstanceID != o.Instance.ID {
		t.Fatal("legacy preview lost internal root pin")
	}
}
