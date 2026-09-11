package server

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/product"
)

func managedPlan(t *testing.T, s *Server, issued map[string]any, action string, explicit bool) map[string]any {
	t.Helper()
	identity := issued["identity"].(map[string]any)
	body := map[string]any{"platform": "hermes", "instance_id": identity["instance_id"], "action": action}
	if explicit {
		body["runtime_identity_id"] = identity["identity_id"]
	}
	code, view := call(t, s, "POST", "/v1/adapter/preview", token, body)
	if code != 200 {
		t.Fatal(code, view)
	}
	if view["schema_version"] != "local-adapter-plan/v3" || view["runtime_identity_id"] != identity["identity_id"] || view["runtime_verified"] != false {
		t.Fatal("wrong managed plan", view)
	}
	return view
}
func managedApplyBody(plan map[string]any) map[string]any {
	return map[string]any{"platform": "hermes", "instance_id": plan["instance_id"], "plan_id": plan["plan_id"], "plan_digest": plan["plan_digest"], "runtime_identity_id": plan["runtime_identity_id"], "actor_id": "operator"}
}
func installedManagedConfig(t *testing.T, s *Server, issued map[string]any) (string, map[string]any) {
	t.Helper()
	id := issued["identity"].(map[string]any)["instance_id"].(string)
	opts, err := s.resolveAdapterOptions("hermes", id)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(opts.Instance.ConfigDir, "plugins", product.PluginDir(), "config.json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cfg map[string]any
	if json.Unmarshal(raw, &cfg) != nil {
		t.Fatal("bad config")
	}
	return path, cfg
}
func TestManagedInstallPreservesIdentityOnRepairAndRevokesOnUninstall(t *testing.T) {
	s, issued, credential, agent := managedIdentityFixture(t, "block")
	plan := managedPlan(t, s, issued, "install", true)
	raw, _ := json.Marshal(plan)
	if strings.Contains(string(raw), credential) || strings.Contains(string(raw), "credential_hash") {
		t.Fatal("plan leaked credential")
	}
	body := managedApplyBody(plan)
	delete(body, "runtime_identity_id")
	if code, _ := call(t, s, "POST", "/v1/adapter/install", token, body); code != 409 {
		t.Fatal("missing identity accepted", code)
	}
	if code, out := call(t, s, "POST", "/v1/adapter/install", token, managedApplyBody(plan)); code != 200 {
		t.Fatal(code, out)
	}
	_, cfg := installedManagedConfig(t, s, issued)
	if cfg["runtime_identity_id"] != plan["runtime_identity_id"] || cfg["agent_id"] != agent || cfg["token_path"] != issued["credential_path"] {
		t.Fatal("managed config mismatch", cfg)
	}
	repair := managedPlan(t, s, issued, "install", false)
	if code, out := call(t, s, "POST", "/v1/adapter/install", token, managedApplyBody(repair)); code != 200 {
		t.Fatal(code, out)
	}
	_, cfg = installedManagedConfig(t, s, issued)
	if cfg["token_path"] != issued["credential_path"] {
		t.Fatal("repair downgraded to global token")
	}
	opts, _ := s.resolveAdapterOptions("hermes", plan["instance_id"].(string))
	diagnosis := s.diagnoseInstance(opts)
	configurationPass, authorityPass := false, false
	for _, check := range diagnosis.Checks {
		configurationPass = configurationPass || check.Code == "service_configuration" && check.Status == "pass"
		authorityPass = authorityPass || check.Code == "instance_authority" && check.Status == "pass"
	}
	if !configurationPass || !authorityPass || diagnosis.RuntimeState != "unverified" {
		t.Fatal("incorrect diagnosis", diagnosis)
	}
	removal := managedPlan(t, s, issued, "uninstall", false)
	for range 2 {
		if code, out := call(t, s, "POST", "/v1/adapter/uninstall", token, managedApplyBody(removal)); code != 200 {
			t.Fatal("uninstall replay", code, out)
		}
	}
	if _, err := s.runtimeIdentities.Authenticate(credential); err == nil {
		t.Fatal("uninstalled credential stayed active")
	}
	summary, err := s.runtimeIdentities.Summary(plan["runtime_identity_id"].(string))
	if err != nil || summary.Status != "revoked" {
		t.Fatal("missing signed revocation", err)
	}
}
func TestManagedPreviewRejectsRevocationAndForeignInstance(t *testing.T) {
	s, issued, _, _ := managedIdentityFixture(t, "block")
	plan := managedPlan(t, s, issued, "install", true)
	rows := instanceFixture(t, s)
	foreign := rows[0].(map[string]any)["instance_id"]
	code, _ := call(t, s, "POST", "/v1/adapter/preview", token, map[string]any{"platform": "hermes", "action": "install", "instance_id": foreign, "runtime_identity_id": plan["runtime_identity_id"]})
	if code != 409 {
		t.Fatal("foreign identity selected", code)
	}
	if _, err := s.runtimeIdentities.Revoke(plan["runtime_identity_id"].(string), "operator"); err != nil {
		t.Fatal(err)
	}
	if code, _ = call(t, s, "POST", "/v1/adapter/install", token, managedApplyBody(plan)); code != 409 {
		t.Fatal("stale active plan applied", code)
	}
	opts, _ := s.resolveAdapterOptions("hermes", plan["instance_id"].(string))
	if _, err := os.Stat(filepath.Join(opts.Instance.ConfigDir, "plugins")); !os.IsNotExist(err) {
		t.Fatal("revoked plan changed host files", err)
	}
}
func TestManagedUninstallFailureKeepsIdentityRevokedAndExternalEdit(t *testing.T) {
	s, issued, credential, _ := managedIdentityFixture(t, "block")
	plan := managedPlan(t, s, issued, "install", true)
	if code, out := call(t, s, "POST", "/v1/adapter/install", token, managedApplyBody(plan)); code != 200 {
		t.Fatal(code, out)
	}
	removal := managedPlan(t, s, issued, "uninstall", false)
	path, cfg := installedManagedConfig(t, s, issued)
	cfg["user_added"] = "retain"
	raw, _ := json.Marshal(cfg)
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	code, out := call(t, s, "POST", "/v1/adapter/uninstall", token, managedApplyBody(removal))
	if code != 409 || out["runtime_identity_revoked"] != true {
		t.Fatal(code, out)
	}
	if _, err := s.runtimeIdentities.Authenticate(credential); err == nil {
		t.Fatal("failed removal resurrected authority")
	}
	current, _ := os.ReadFile(path)
	if string(current) != string(raw) {
		t.Fatal("external edit lost")
	}
	opts, _ := s.resolveAdapterOptions("hermes", plan["instance_id"].(string))
	if s.diagnoseInstance(opts).ConfigurationState != "incomplete" {
		t.Fatal("revoked config considered ready")
	}
}
func TestDirectManagedUninstallRequiresPriorWithdrawal(t *testing.T) {
	s, issued, _, _ := managedIdentityFixture(t, "block")
	plan := managedPlan(t, s, issued, "install", true)
	if code, out := call(t, s, "POST", "/v1/adapter/install", token, managedApplyBody(plan)); code != 200 {
		t.Fatal(code, out)
	}
	opts, _ := s.resolveAdapterOptions("hermes", plan["instance_id"].(string))
	preview, err := adapterinstall.Prepare(opts, "uninstall")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = adapterinstall.Apply(preview); err != adapterinstall.ErrIdentityWithdrawalRequired {
		t.Fatal("package caller removed active hooks", err)
	}
}

func TestManagedDiagnosisRejectsIdentityFromAnotherInstance(t *testing.T) {
	s, issued, _, _ := managedIdentityFixture(t, "block")
	rows := instanceFixture(t, s)
	own := issued["identity"].(map[string]any)["instance_id"].(string)
	var foreign string
	for _, row := range rows {
		id := row.(map[string]any)["instance_id"].(string)
		if id != own {
			foreign = id
			break
		}
	}
	if foreign == "" {
		t.Fatal("missing distinct fixture instance")
	}
	opts, err := s.resolveAdapterOptions("hermes", foreign)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(opts.Instance.ConfigDir, "plugins", product.PluginDir(), "config.json")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(map[string]any{"runtime_identity_id": issued["identity"].(map[string]any)["identity_id"], "agent_id": "hri-" + strings.TrimPrefix(foreign, "hi-"), "token_path": issued["credential_path"], "endpoint": opts.Endpoint, "enforcement_mode": opts.Mode})
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	diagnosis := s.diagnoseInstance(opts)
	for _, check := range diagnosis.Checks {
		if check.Code == "instance_authority" {
			if check.Status != "fail" {
				t.Fatal("foreign authority reported valid", diagnosis)
			}
			return
		}
	}
	t.Fatal("authority diagnosis missing")
}

func TestManagedPlanV3ContractFixture(t *testing.T) {
	s, issued, _, _ := managedIdentityFixture(t, "block")
	plan := managedPlan(t, s, issued, "install", true)
	plan["plan_id"] = "ap-" + strings.Repeat("0", 32)
	plan["plan_digest"] = strings.Repeat("0", 64)
	plan["instance_id"] = "hi-" + strings.Repeat("0", 32)
	plan["runtime_identity_id"] = "ri-" + strings.Repeat("0", 32)
	plan["expires_at"] = "2026-09-10T09:00:00Z"
	for _, item := range plan["changes"].([]any) {
		row := item.(map[string]any)
		for _, key := range []string{"before_sha256", "after_sha256"} {
			if row[key] != "" {
				row[key] = strings.Repeat("0", 64)
			}
		}
	}
	raw, err := json.MarshalIndent(plan, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	raw = append(raw, '\n')
	path := filepath.Join("..", "..", "testdata", "contracts", "adapter-plan.v3.json")
	if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
		if err := os.WriteFile(path, raw, 0644); err != nil {
			t.Fatal(err)
		}
	}
	expected, err := os.ReadFile(path)
	if err != nil || string(expected) != string(raw) {
		t.Fatal("managed plan contract drift", err)
	}
}
