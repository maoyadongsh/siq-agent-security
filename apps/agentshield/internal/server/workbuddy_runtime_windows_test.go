package server

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

// Component evidence: real state/NTFS and production HTTP admit, instance-draft,
// resource approval and session stores. This does not execute a desktop/model.
func TestWorkBuddyWindowsManagedHTTPAuthority(t *testing.T) {
	f := newWindowsAuthorityHTTPFixtureForPlatform(t, "block", false, "workbuddy")
	listed := windowsAuthorityHTTP(t, f.s, "GET", "/v1/adapter/instances?platform=workbuddy", f.s.bootAdmin, nil, 200)
	if listed["schema_version"] != "local-adapter-instances/v2" || listed["managed_runtime_available"] != true || listed["native_available"] != false {
		t.Fatal("incorrect managed capability", listed)
	}
	if _, err := f.s.resolveSkillTarget(context.Background(), f.instance); err == nil {
		t.Fatal("WorkBuddy unexpectedly enabled Skill installation")
	}
	enroll := map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": f.session}
	first := windowsAuthorityHTTP(t, f.s, "POST", "/v1/runtime-sessions", f.credential, enroll, 200)
	second := windowsAuthorityHTTP(t, f.s, "POST", "/v1/runtime-sessions", f.credential, enroll, 200)
	if first["schema_version"] != "local-runtime-session-enrolled/v2" || first["platform"] != "workbuddy" || first["expires_at"] != second["expires_at"] || first["binding_id"] != second["binding_id"] {
		t.Fatal("enrollment changed immutable binding", first, second)
	}
	identities := windowsAuthorityHTTP(t, f.s, "GET", "/v1/runtime-identities", f.s.bootAdmin, nil, 200)
	workBuddyContractSample(t, "local-runtime-identities.v2", identities)
	call, _ := runtimeidentity.WorkBuddyCallID("windows-authority-http", "read-1")
	body := f.decision("read_file", call, f.input)
	allowed := windowsAuthorityHTTP(t, f.s, "POST", "/v1/decide", f.credential, body, 200)
	if allowed["action"] != "allow" || allowed["authority_status"] != "valid" {
		t.Fatal("valid Windows WorkBuddy authority rejected", allowed)
	}
	body["result"] = "component observation"
	observed := windowsAuthorityHTTP(t, f.s, "POST", "/v1/observe", f.credential, body, 200)
	if observed["action_id"] != allowed["action_id"] {
		t.Fatal("observation escaped decision")
	}
	delete(body, "result")
	for _, route := range []string{"/v1/decide", "/v1/observe"} {
		for _, bad := range []string{"", "raw-call", strings.ToUpper(call), f.session} {
			body["tool_call_id"] = bad
			windowsAuthorityHTTP(t, f.s, "POST", route, f.credential, body, 400)
		}
		body["tool_call_id"] = call
		raw, _ := json.Marshal(body)
		for _, bad := range []string{strings.Replace(string(raw), `"tool_call_id":`, `"Tool_Call_Id":`, 1), `{"tool_call_id":"` + call + `",` + string(raw)[1:]} {
			windowsAuthorityHTTP(t, f.s, "POST", route, f.credential, bad, 400)
		}
	}
	for _, field := range []string{"platform", "agent_id", "session_id"} {
		original := body[field]
		body[field] = "foreign"
		windowsAuthorityHTTP(t, f.s, "POST", "/v1/decide", f.credential, body, 401)
		body[field] = original
	}
	windowsAuthorityHTTP(t, f.s, "POST", "/v1/decide", f.s.d.Token, body, 403)
	for _, bad := range []string{"raw-host-session", strings.ToUpper(f.session), call} {
		enroll["session_id"] = bad
		windowsAuthorityHTTP(t, f.s, "POST", "/v1/runtime-sessions", f.credential, enroll, 400)
	}
	create := map[string]any{"schema_version": "local-runtime-identity-create/v1", "instance_id": f.instance, "grant_id": f.grantID, "expected_grant_revision": f.revision, "actor_id": "component-operator", "session_ttl_seconds": 3600}
	windowsAuthorityHTTP(t, f.s, "POST", "/v1/runtime-identities", f.s.bootAdmin, create, 400)
	call, _ = runtimeidentity.WorkBuddyCallID("windows-authority-http", "outside-1")
	denied := windowsAuthorityHTTP(t, f.s, "POST", "/v1/decide", f.credential, f.decision("write_file", call, f.outside), 200)
	if denied["action"] != "deny" {
		t.Fatal("out-of-scope write accepted", denied)
	}
	if _, err := os.Stat(f.outside); !os.IsNotExist(err) {
		t.Fatal("denial wrote outside scope", err)
	}
	root, _, err := f.s.workBuddyRoot()
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("WORKBUDDY_CONFIG_DIR", root+"-missing")
	windowsAuthorityHTTP(t, f.s, "POST", "/v1/decide", f.credential, body, 401)
	t.Setenv("WORKBUDDY_CONFIG_DIR", root)
	windowsAuthorityHTTP(t, f.s, "POST", "/v1/runtime-identities/"+f.identityID+"/revoke", f.s.bootAdmin, map[string]any{"schema_version": "local-runtime-identity-revoke/v1", "actor_id": "component-operator"}, 200)
	windowsAuthorityHTTP(t, f.s, "POST", "/v1/decide", f.credential, body, 401)
	enroll["session_id"] = f.session
	windowsAuthorityHTTP(t, f.s, "POST", "/v1/runtime-sessions", f.credential, enroll, 401)
	records, err := f.s.d.Chain.Read()
	if err != nil || len(records) != 3 || receipt.Verify(records, f.s.d.Key.Public()) != nil {
		t.Fatal("signed decision/observation chain invalid", err, len(records))
	}
}

func TestWorkBuddyWindowsInventoryAmbiguityAndRawAliases(t *testing.T) {
	home := t.TempDir()
	root := filepath.Join(home, ".workbuddy")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "config.yaml"), []byte("model: fixture\n"), 0600); err != nil {
		t.Fatal(err)
	}
	s := &Server{d: Deps{Home: home}}
	list := func() map[string]any {
		w := httptest.NewRecorder()
		s.workBuddyInstanceRow(w)
		var result map[string]any
		if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &result) != nil {
			t.Fatal("invalid listing")
		}
		return result
	}
	t.Setenv("WORKBUDDY_CONFIG_DIR", root+`\..\.workbuddy`)
	listing := list()
	if listing["managed_runtime_available"] != false || len(listing["instances"].([]any)) != 0 {
		t.Fatal("raw alias hidden by cleaning", listing)
	}
	t.Setenv("WORKBUDDY_CONFIG_DIR", root)
	s.d.HermesHome = root
	listing = list()
	if listing["managed_runtime_available"] != false || len(listing["instances"].([]any)) != 0 {
		t.Fatal("cross-platform ambiguous root accepted", listing)
	}
}
