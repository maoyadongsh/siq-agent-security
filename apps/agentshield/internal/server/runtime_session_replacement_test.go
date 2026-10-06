package server

import (
	"os"
	"testing"
)

func TestRuntimeSessionReplacementWithRevokedGrantReportsConflict(t *testing.T) {
	s, issued, credential, agent := managedIdentityFixture(t, "block")
	old := issued["identity"].(map[string]any)
	enroll := map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": "old-installed-skill-session"}
	code, binding := scopedCall(t, s, "/v1/runtime-sessions", credential, enroll)
	if code != 200 {
		t.Fatal(code, binding)
	}
	ref := old["grant_ref"].(map[string]any)
	grantRoute := "/v1/grants/" + ref["grant_id"].(string)
	code, view := call(t, s, "GET", grantRoute, token, nil)
	if code != 200 {
		t.Fatal(code, view)
	}
	code, out := call(t, s, "POST", grantRoute+"/revoke", token, map[string]any{
		"expected_revision": view["state_revision"], "actor_id": "operator"})
	if code != 200 {
		t.Fatal(code, out)
	}
	code, out = call(t, s, "POST", "/v1/runtime-identities/"+old["identity_id"].(string)+"/revoke", token,
		map[string]any{"schema_version": "local-runtime-identity-revoke/v1", "actor_id": "operator"})
	if code != 200 {
		t.Fatal(code, out)
	}
	g, revision := selectedGrantFixture(t, s, s.d.Store, "d", "/work/public", false, agent)
	code, fresh := call(t, s, "POST", "/v1/runtime-identities", token, map[string]any{
		"schema_version": "local-runtime-identity-create/v1", "instance_id": old["instance_id"],
		"grant_id": g.GrantID, "expected_grant_revision": revision,
		"actor_id": "operator", "session_ttl_seconds": 600})
	if code != 201 {
		t.Fatal(code, fresh)
	}
	raw, err := os.ReadFile(fresh["credential_path"].(string))
	if err != nil {
		t.Fatal(err)
	}
	for attempt := 0; attempt < 2; attempt++ {
		code, out = scopedCall(t, s, "/v1/runtime-sessions", string(raw), enroll)
		if code != 409 || out["error"] != "runtime_identity_authority_conflict" {
			t.Fatal("old session conflict misclassified or accepted", code, out)
		}
	}
	if code, _ = scopedCall(t, s, "/v1/runtime-sessions", credential, enroll); code != 401 {
		t.Fatal("old credential revived", code)
	}
	historical, err := s.intents.HistoricalBinding("hermes", enroll["session_id"].(string), agent)
	if err != nil || historical.BindingID != binding["binding_id"] || historical.GrantRef.GrantID != ref["grant_id"] {
		t.Fatal("historical binding replaced", err)
	}
	enroll["session_id"] = "fresh-updated-skill-session"
	code, out = scopedCall(t, s, "/v1/runtime-sessions", string(raw), enroll)
	if code != 200 || out["identity_id"] == old["identity_id"] {
		t.Fatal("fresh identity utility lost", code, out)
	}
}
