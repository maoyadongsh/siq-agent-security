package adapterinstall

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/adapters"
)

func workBuddyManagedOptions(t *testing.T) Options {
	t.Helper()
	o := testOpts(t, WorkBuddy)
	root := configDir(o.Home, WorkBuddy)
	putTestFile(t, filepath.Join(root, "settings.json"), []byte(`{"enabledPlugins":{"builtin":true},"user_setting":"before"}`), 0600)
	o = WithWorkBuddyInstance(o, root)
	o.RuntimeIdentityID = "ri-" + strings.Repeat("c", 32)
	raw, _ := json.Marshal(map[string]any{"schema_version": "local-runtime-identity/v2", "filesystem_profile": "windows-local-drive/v1", "identity_id": o.RuntimeIdentityID, "instance_id": o.Instance.ID, "agent_id": "hri-" + strings.TrimPrefix(o.Instance.ID, "hi-"), "platform": WorkBuddy})
	putTestFile(t, filepath.Join(o.StateDir, "runtime-identities", o.RuntimeIdentityID+".json"), raw, 0600)
	return o
}

func TestWorkBuddyManagedInstallDiagnosisAndRevokedUninstall(t *testing.T) {
	o := workBuddyManagedOptions(t)
	settings := filepath.Join(o.configRoot(), "settings.json")
	original, _ := os.ReadFile(settings)
	p, err := Prepare(o, "install")
	if err != nil {
		t.Fatal(err)
	}
	if p.View().SchemaVersion != "local-adapter-plan/v4" || p.View().RuntimeIdentityID != o.RuntimeIdentityID {
		t.Fatalf("wrong versioned plan: %+v", p.View())
	}
	for path := range p.payload.Inputs {
		if strings.Contains(path, "runtime-identity-secrets") {
			t.Fatal("plan read secret")
		}
	}
	if _, err := Apply(p); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(workBuddyManagedConfigPath(o))
	if err != nil {
		t.Fatal(err)
	}
	cfg, err := adapters.DecodeWorkBuddyManagedConfig(raw, workBuddyManagedConfigPath(o), o.StateDir)
	if err != nil || cfg.RuntimeIdentityID != o.RuntimeIdentityID {
		t.Fatalf("managed config: %+v %v", cfg, err)
	}
	if id, err := ConfiguredRuntimeIdentity(o); err != nil || id != o.RuntimeIdentityID {
		t.Fatal("identity readback failed", id, err)
	}
	if endpoint, ok := ConfiguredEndpoint(o); !ok || endpoint != o.Endpoint {
		t.Fatal("endpoint readback failed")
	}
	d := Inspect(o)
	if checkStatus(d, "host_registration") != "pass" || checkStatus(d, "service_configuration") != "pass" || d.RuntimeState != "unverified" {
		t.Fatalf("wrong diagnosis: %+v", d)
	}
	var doc map[string]any
	raw, _ = os.ReadFile(settings)
	_ = json.Unmarshal(raw, &doc)
	if !hostHookRegisteredCommand(doc, workBuddyManagedCommand(o.Binary, o)) || strings.Count(string(raw), "--managed-config") != 2 {
		t.Fatal("managed commands missing")
	}
	if _, err := Install(o); err != nil {
		t.Fatal("idempotent repair failed", err)
	}
	backup, err := os.ReadFile(settings + originalSuffix)
	if err != nil || string(backup) != string(original) {
		t.Fatal("first backup replaced")
	}
	if _, err := Uninstall(o); !errors.Is(err, ErrIdentityWithdrawalRequired) {
		t.Fatal("live identity removed", err)
	}
	doc["later_user_edit"] = true
	raw, _ = json.Marshal(doc)
	putTestFile(t, settings, raw, 0600)
	putTestFile(t, managedRevocationPath(o), []byte(`{"revoked":true}`), 0600)
	if _, err := Uninstall(o); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(workBuddyManagedConfigPath(o)); !os.IsNotExist(err) {
		t.Fatal("owned managed config survived uninstall")
	}
	raw, _ = os.ReadFile(settings)
	_ = json.Unmarshal(raw, &doc)
	if strings.Contains(string(raw), "hook workbuddy") || doc["later_user_edit"] != true || doc["enabledPlugins"].(map[string]any)["builtin"] != true {
		t.Fatal("uninstall damaged unrelated configuration")
	}
}

func TestWorkBuddyManagedNeverDowngradesAndDetectsMissingConfig(t *testing.T) {
	o := workBuddyManagedOptions(t)
	if _, err := Install(o); err != nil {
		t.Fatal(err)
	}
	// A caller omitting identity reuses the recorded identity, never global token.
	legacy := o
	legacy.Instance = nil
	legacy.RuntimeIdentityID = ""
	p, err := Prepare(legacy, "install")
	if err != nil || p.View().RuntimeIdentityID != o.RuntimeIdentityID {
		t.Fatal("managed repair downgraded", err)
	}
	if err := os.Remove(workBuddyManagedConfigPath(o)); err != nil {
		t.Fatal(err)
	}
	path, managed, err := WorkBuddyManagedConfigReference(o.Home, o.StateDir)
	if err != nil || !managed || path != workBuddyManagedConfigPath(o) {
		t.Fatal("recorded managed path fell back", path, managed, err)
	}
	d := Inspect(o)
	if checkStatus(d, "service_configuration") != "fail" {
		t.Fatal("missing managed config diagnosed ready")
	}
	// Unknown managed state is not overwritten by an unselected legacy install.
	fresh := workBuddyManagedOptions(t)
	raw, _ := json.Marshal(map[string]any{"runtime_identity_id": fresh.RuntimeIdentityID})
	putTestFile(t, workBuddyManagedConfigPath(fresh), raw, 0600)
	fresh.RuntimeIdentityID = ""
	if _, err := Prepare(fresh, "install"); !errors.Is(err, ErrPlanChanged) {
		t.Fatal("unknown managed configuration overwritten", err)
	}
}

func TestWorkBuddyManagedPinRejectsOldProfileAndChangedMetadata(t *testing.T) {
	for _, kind := range []string{"v1", "foreign-platform", "revoked", "changed-after-preview"} {
		t.Run(kind, func(t *testing.T) {
			o := workBuddyManagedOptions(t)
			path := filepath.Join(o.StateDir, "runtime-identities", o.RuntimeIdentityID+".json")
			if kind == "changed-after-preview" {
				p, err := Prepare(o, "install")
				if err != nil {
					t.Fatal(err)
				}
				putTestFile(t, path, []byte(`{}`), 0600)
				if _, err := Apply(p); !errors.Is(err, ErrPlanChanged) {
					t.Fatal("stale metadata applied", err)
				}
				return
			}
			if kind == "revoked" {
				putTestFile(t, managedRevocationPath(o), []byte(`{}`), 0600)
			} else {
				raw, _ := os.ReadFile(path)
				text := string(raw)
				if kind == "v1" {
					text = strings.Replace(text, "local-runtime-identity/v2", "local-runtime-identity/v1", 1)
				} else {
					text = strings.Replace(text, `"platform":"workbuddy"`, `"platform":"hermes"`, 1)
				}
				putTestFile(t, path, []byte(text), 0600)
			}
			if _, err := Prepare(o, "install"); !errors.Is(err, ErrPlanChanged) {
				t.Fatal("bad managed authority accepted", err)
			}
		})
	}
}
