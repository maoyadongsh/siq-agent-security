package adapterinstall

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/state"
)

func installedPlan(t *testing.T, platform string) (Options, *Plan) {
	t.Helper()
	o := testOpts(t, platform)
	p := testPlan(t, o, "install")
	if _, err := Apply(p); err != nil {
		t.Fatal(err)
	}
	return o, p
}

func TestIntegrityDeletedInstallationIsNotFresh(t *testing.T) {
	for _, platform := range []string{Hermes, OpenClaw, WorkBuddy} {
		t.Run(platform, func(t *testing.T) {
			o, _ := installedPlan(t, platform)
			if err := os.RemoveAll(o.configRoot()); err != nil {
				t.Fatal(err)
			}
			d := Inspect(o)
			if d.ConfigurationState != "incomplete" || d.RuntimeState != "unverified" || checkStatus(d, "adapter_files") != "fail" {
				t.Fatalf("lost installation hidden: %+v", d)
			}
		})
	}
}

func TestIntegrityCorruptSealedInstallIsNotReady(t *testing.T) {
	o, p := installedPlan(t, OpenClaw)
	path := transactionPath(o.StateDir, p.payload.View.PlanID, ".sealed")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	raw[len(raw)-1] ^= 1
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	d := Inspect(o)
	if d.ConfigurationState != "incomplete" || checkStatus(d, "installation_record") != "fail" {
		t.Fatalf("corrupt ownership hidden: %+v", d)
	}
	got, _ := os.ReadFile(path)
	if string(got) != string(raw) {
		t.Fatal("diagnostic changed failed evidence")
	}
}

func TestIntegrityForgedUninstallCannotHideInstall(t *testing.T) {
	o, p := installedPlan(t, OpenClaw)
	st := &state.Store{Dir: o.StateDir}
	rev, raw, err := st.LatestSeq("adapter-operations", operationKey(o))
	if err != nil {
		t.Fatal(err)
	}
	var claim operationClaim
	if err := json.Unmarshal(raw, &claim); err != nil {
		t.Fatal(err)
	}
	claim.Action = "uninstall"
	forged, _ := json.Marshal(claim)
	path := filepath.Join(o.StateDir, "adapter-operations", operationKey(o)+".0.json")
	if rev != 0 {
		t.Fatal("unexpected fixture revision")
	}
	if err := os.WriteFile(path, forged, 0600); err != nil {
		t.Fatal(err)
	}
	// The existing matching committed end record remains. The authenticated plan is install.
	_, _, err = latestManagedRecord(o.StateDir, o.Platform, operationKey(o))
	if err == nil || err == errNoInstallRecord {
		t.Fatalf("unverified action accepted as uninstall: %v", err)
	}
	if d := Inspect(o); d.ConfigurationState != "incomplete" || checkStatus(d, "installation_record") != "fail" {
		t.Fatalf("forged action hidden: %+v", d)
	}
	if _, err := os.Stat(transactionPath(o.StateDir, p.payload.View.PlanID, ".sealed")); err != nil {
		t.Fatal(err)
	}
}

func TestIntegrityValidInstallAndUninstall(t *testing.T) {
	for _, platform := range []string{Hermes, OpenClaw, WorkBuddy} {
		t.Run(platform, func(t *testing.T) {
			o, _ := installedPlan(t, platform)
			if d := Inspect(o); checkStatus(d, "installation_record") != "pass" || d.RuntimeState != "unverified" {
				t.Fatalf("valid record not inspected: %+v", d)
			}
			if _, err := Uninstall(o); err != nil {
				t.Fatal(err)
			}
			if d := Inspect(o); d.ConfigurationState != "not_installed" {
				t.Fatalf("valid uninstall rejected: %+v", d)
			}
		})
	}
}

func TestIntegrityReplacedPluginManifestRemainsDrift(t *testing.T) {
	for _, platform := range []string{Hermes, OpenClaw} {
		t.Run(platform, func(t *testing.T) {
			o, _ := installedPlan(t, platform)
			name := "plugin.yaml"
			if platform == OpenClaw {
				name = "openclaw.plugin.json"
			}
			path := filepath.Join(o.configRoot(), "plugins", "siq-agent-security", name)
			putTestFile(t, path, []byte("replacement-manifest"), 0600)
			d := Inspect(o)
			if d.ConfigurationState != "incomplete" || checkStatus(d, "adapter_files") != "fail" || checkStatus(d, "installation_record") != "pass" {
				t.Fatalf("plugin manifest replaced independent expectation: %+v", d)
			}
		})
	}
}

func TestIntegrityInterruptedUpgradeAndRecovery(t *testing.T) {
	o, _ := installedPlan(t, OpenClaw)
	// Change only a reviewed connection setting; emulate lost acknowledgement
	// after the actual plan has applied and before its completion record survives.
	o.Mode = "warn"
	p := testPlan(t, o, "install")
	if _, err := Apply(p); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(transactionPath(o.StateDir, p.payload.View.PlanID, ".end.json")); err != nil {
		t.Fatal(err)
	}
	d := Inspect(o)
	if d.ConfigurationState != "incomplete" || checkStatus(d, "installation_record") != "fail" {
		t.Fatalf("interrupted upgrade hidden: %+v", d)
	}
	if _, err := Recover(o.StateDir, o.Platform); err != nil {
		t.Fatal(err)
	}
	assertBefore(t, p)
	o.Mode = "block"
	d = Inspect(o)
	if d.ConfigurationState != "ready" || checkStatus(d, "installation_record") != "pass" {
		t.Fatalf("prior install not restored: %+v", d)
	}
}

func TestIntegrityDiagnosisContractSample(t *testing.T) {
	o, p := installedPlan(t, OpenClaw)
	good := Inspect(o)
	if err := os.Remove(transactionPath(o.StateDir, p.payload.View.PlanID, ".sealed")); err != nil {
		t.Fatal(err)
	}
	bad := Inspect(o)
	if checkStatus(good, "installation_record") != "pass" || checkStatus(bad, "installation_record") != "fail" {
		t.Fatal("unexpected sample")
	}
	raw, err := json.MarshalIndent(map[string]any{"schema_version": "local-adapter-diagnostics/v1", "platform_changes": false, "platforms": []Diagnosis{good, bad}}, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	expected, err := os.ReadFile(filepath.Join("..", "..", "testdata", "contracts", "adapter-diagnostics-integrity.json"))
	if err != nil || !bytes.Equal(bytes.TrimSpace(expected), raw) {
		t.Fatal("diagnosis contract sample differs", err)
	}
}
