package server

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/state"
)

// OpenClaw identity fixture: default config root, platform-locked grant.
func openClawIdentityFixture(t *testing.T, s *Server, st *state.Store) (string, string, map[string]any, string) {
	t.Helper()
	root := filepath.Join(s.d.Home, ".openclaw")
	if err := os.MkdirAll(root, 0700); err != nil {
		t.Fatal(err)
	}
	instance := hermeshome.Identifier(root)
	agent, _ := runtimeidentity.AgentID(instance)
	facts := []admission.DeclaredFact{}
	for _, tool := range []string{"read_file", "write_file", "web_fetch"} {
		facts = append(facts, admission.DeclaredFact{Domain: "tool", Action: "tool.invoke", Resource: admission.Resource{Type: "tool", Value: tool}, Effect: "allow", State: "declared", Authority: "skill_manifest"})
	}
	facts = append(facts, admission.DeclaredFact{Domain: "filesystem", Action: "fs.write", Resource: admission.Resource{Type: "path", Value: "/work/public"}, Effect: "allow", State: "declared", Authority: "skill_manifest"})
	r, err := grant.Build(admission.Admission{AdmissionID: "adm-oc", ContentHash: strings.Repeat("c", 64), Verdict: "admit", DeclaredFacts: facts}, grant.Options{Platform: "openclaw", Subject: grant.Subject{Type: "agent_instance", ID: agent}, Now: time.Date(2026, 9, 13, 6, 0, 0, 0, time.UTC), Key: s.d.Key})
	if err != nil {
		t.Fatal(err)
	}
	g, err := grant.Approve(r.Grant, grant.Approval{ActorType: "human", ActorID: "fixture-operator", ApprovedAt: time.Now().UTC().Format(time.RFC3339), Channel: "console"}, s.d.Key)
	if err != nil {
		t.Fatal(err)
	}
	g, err = grant.MarkDeployed(g, s.d.Key)
	if err != nil {
		t.Fatal(err)
	}
	rev, err := st.PutGrantCAS(g, -1)
	if err != nil {
		t.Fatal(err)
	}
	req := map[string]any{"schema_version": "local-runtime-identity-create/v1", "instance_id": instance, "grant_id": g.GrantID, "expected_grant_revision": rev, "actor_id": "operator", "session_ttl_seconds": 28800}
	code, out := call(t, s, "POST", "/v1/runtime-identities", token, req)
	if code != 201 {
		t.Fatal(code, out)
	}
	if out["identity"].(map[string]any)["platform"] != "openclaw" {
		t.Fatal("identity platform not locked to openclaw", out)
	}
	raw, err := os.ReadFile(out["credential_path"].(string))
	if err != nil {
		t.Fatal(err)
	}
	return instance, agent, out, string(raw)
}

func TestOpenClawManagedInstallDecisionsAndRevocation(t *testing.T) {
	s, st := grantBindingServer(t, "block")
	instance, agent, issued, credential := openClawIdentityFixture(t, s, st)
	id := issued["identity"].(map[string]any)["identity_id"].(string)

	code, list := call(t, s, "GET", "/v1/adapter/instances?platform=openclaw", token, nil)
	if code != 200 {
		t.Fatal(list)
	}
	rows := list["instances"].([]any)
	if list["native_available"] != false {
		t.Fatal("unverified native capture claimed available", list)
	}
	if len(rows) != 1 || rows[0].(map[string]any)["instance_id"] != instance {
		t.Fatal("openclaw instance listing wrong", rows)
	}
	// The same content-derived ID cannot be resolved as a Hermes profile.
	if code, _ := call(t, s, "POST", "/v1/adapter/preview", token, map[string]any{"platform": "hermes", "action": "install", "instance_id": instance}); code != 409 {
		t.Fatal("cross-platform instance accepted", code)
	}

	preview := func(action string) map[string]any {
		t.Helper()
		code, view := call(t, s, "POST", "/v1/adapter/preview", token, map[string]any{"platform": "openclaw", "action": action, "instance_id": instance, "runtime_identity_id": id})
		if code != 200 || view["schema_version"] != "local-adapter-plan/v3" || view["runtime_identity_id"] != id {
			t.Fatal("wrong openclaw plan", code, view)
		}
		return view
	}
	plan := preview("install")
	if code, out := call(t, s, "POST", "/v1/adapter/install", token, map[string]any{"platform": "openclaw", "instance_id": instance, "plan_id": plan["plan_id"], "plan_digest": plan["plan_digest"], "runtime_identity_id": id, "actor_id": "operator"}); code != 200 {
		t.Fatal(code, out)
	}
	raw, err := os.ReadFile(filepath.Join(s.d.Home, ".openclaw", product.Name+".json"))
	if err != nil {
		t.Fatal(err)
	}
	var cfg map[string]any
	if json.Unmarshal(raw, &cfg) != nil {
		t.Fatal("product config invalid")
	}
	if cfg["runtimeIdentityId"] != id || cfg["agentId"] != agent || cfg["tokenPath"] != issued["credential_path"] {
		t.Fatalf("managed fields not pinned: %v", cfg)
	}

	session, err := intent.OpenClawSessionID("openclaw-native", "11111111-1111-4111-8111-111111111111")
	if err != nil {
		t.Fatal(err)
	}
	if code, _ := scopedCall(t, s, "/v1/runtime-sessions", credential, map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": session}); code != 200 {
		t.Fatal("enrollment rejected")
	}
	decision := map[string]any{"platform": "openclaw", "agent_id": agent, "session_id": session, "tool": "read_file", "params": map[string]any{"path": "/work/public/report"}}
	if code, out := scopedCall(t, s, "/v1/decide", credential, decision); code != 200 || out["action"] != "allow" || out["authority_status"] != "valid" {
		t.Fatal(code, out)
	}
	// Platform lock also holds at the HTTP boundary.
	decision["platform"] = "hermes"
	if code, _ := scopedCall(t, s, "/v1/decide", credential, decision); code != 401 {
		t.Fatal("openclaw credential decided as hermes")
	}

	opts, err := s.resolveAdapterOptions("openclaw", instance)
	if err != nil {
		t.Fatal(err)
	}
	diagnosis := s.diagnoseInstance(opts)
	seen := map[string]string{}
	for _, check := range diagnosis.Checks {
		seen[check.Code] = check.Status
	}
	for _, code := range []string{"adapter_files", "service_configuration", "host_registration", "instance_authority"} {
		if seen[code] != "pass" {
			t.Fatalf("diagnosis %s = %q", code, seen[code])
		}
	}

	removal := preview("uninstall")
	for range 2 {
		if code, out := call(t, s, "POST", "/v1/adapter/uninstall", token, map[string]any{"platform": "openclaw", "instance_id": instance, "plan_id": removal["plan_id"], "plan_digest": removal["plan_digest"], "runtime_identity_id": id, "actor_id": "operator"}); code != 200 {
			t.Fatal("uninstall replay", code, out)
		}
	}
	if _, err := s.runtimeIdentities.Authenticate(credential); err == nil {
		t.Fatal("uninstalled openclaw credential stayed active")
	}
	summary, err := s.runtimeIdentities.Summary(id)
	if err != nil || summary.Status != "revoked" {
		t.Fatal("missing signed revocation", err)
	}
}
