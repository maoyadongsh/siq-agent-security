package server

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

func managedIdentityFixture(t *testing.T, mode string) (*Server, map[string]any, string, string) {
	t.Helper()
	s, st := grantBindingServer(t, mode)
	rows := instanceFixture(t, s)
	id := rows[1].(map[string]any)["instance_id"].(string)
	agent, _ := runtimeidentity.AgentID(id)
	g, rev := selectedGrantFixture(t, s, st, "c", "/work/public", false, agent)
	req := map[string]any{"schema_version": "local-runtime-identity-create/v1", "instance_id": id, "grant_id": g.GrantID, "expected_grant_revision": rev, "actor_id": "operator", "session_ttl_seconds": 28800}
	code, out := call(t, s, "POST", "/v1/runtime-identities", token, req)
	if code != 201 {
		t.Fatal(code, out)
	}
	path := out["credential_path"].(string)
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	serialized, _ := json.Marshal(out)
	if strings.Contains(string(serialized), string(raw)) || strings.Contains(string(serialized), "credential_hash") {
		t.Fatal("credential leaked")
	}
	return s, out, string(raw), agent
}
func scopedCall(t *testing.T, s *Server, path, credential string, body any) (int, map[string]any) {
	t.Helper()
	req := loopbackRequest("POST", path, body)
	req.Header.Set("Authorization", "Bearer "+credential)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	out := map[string]any{}
	_ = json.Unmarshal(w.Body.Bytes(), &out)
	return w.Code, out
}
func TestRuntimeIdentityHTTPDecisionIsolationAndRevocation(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		t.Run(mode, func(t *testing.T) {
			s, issued, credential, agent := managedIdentityFixture(t, mode)
			request := map[string]any{"platform": "hermes", "agent_id": agent, "session_id": "native-session", "tool": "read_file", "params": map[string]any{"path": "/work/public/report"}}
			if code, _ := scopedCall(t, s, "/v1/decide", credential, request); code != 401 {
				t.Fatal("unenrolled request accepted", code)
			}
			enroll := map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": "native-session"}
			code, b := scopedCall(t, s, "/v1/runtime-sessions", credential, enroll)
			if code != 200 || b["agent_id"] != agent {
				t.Fatal(code, b)
			}
			for _, other := range []string{token, s.bootAdmin, strings.Repeat("b", 64)} {
				code, _ = scopedCall(t, s, "/v1/decide", other, request)
				if code != 401 && code != 403 {
					t.Fatal("borrowed managed subject", code)
				}
			}
			code, out := scopedCall(t, s, "/v1/decide", credential, request)
			if code != 200 || out["action"] != "allow" || out["authority_status"] != "valid" {
				t.Fatal(code, out)
			}
			records, err := s.d.Chain.Read()
			if err != nil || len(records) == 0 || records[len(records)-1].IntentID != b["intent_id"] {
				t.Fatal("missing fixed session evidence", err)
			}
			request["params"] = map[string]any{"path": "/work/private/report"}
			code, out = scopedCall(t, s, "/v1/decide", credential, request)
			if code != 200 || out["policy_action"] != "deny" {
				t.Fatal(code, out)
			}
			if mode == "block" && out["action"] != "deny" || mode != "block" && out["action"] != "allow" {
				t.Fatal("policy mode changed", out)
			}
			for _, route := range []string{"/v1/decide", "/v1/observe", "/v1/hold-status", "/v1/provenance-reports", "/v1/provenance-select", "/v1/tool-effect-reports"} {
				request["session_id"] = "other-session"
				if code, _ = scopedCall(t, s, route, credential, request); code != 401 {
					t.Fatal("cross-session", route, code)
				}
				request["session_id"] = "native-session"
				if code, _ = scopedCall(t, s, route, token, request); code != 403 {
					t.Fatal("global borrowed reserved subject", route, code)
				}
			}
			id := issued["identity"].(map[string]any)["identity_id"].(string)
			code, out = call(t, s, "POST", "/v1/runtime-identities/"+id+"/revoke", token, map[string]any{"schema_version": "local-runtime-identity-revoke/v1", "actor_id": "operator"})
			if code != 200 || out["revoked"] != true {
				t.Fatal(code, out)
			}
			if code, _ = scopedCall(t, s, "/v1/decide", credential, request); code != 401 {
				t.Fatal("revoked credential accepted", code)
			}
			if code, _ = scopedCall(t, s, "/v1/runtime-sessions", credential, enroll); code != 401 {
				t.Fatal("revoked identity re-enrolled", code)
			}
			code, out = call(t, s, "GET", "/v1/runtime-identities", token, nil)
			if code != 200 {
				t.Fatal(code, out)
			}
			row := out["items"].([]any)[0].(map[string]any)
			if row["status"] != "revoked" || row["runtime_state"] != "unverified" {
				t.Fatal(row)
			}
		})
	}
}
func TestRuntimeIdentityHTTPStrictRequestsAndCapabilities(t *testing.T) {
	s, _, credential, _ := managedIdentityFixture(t, "block")
	for _, other := range []string{token, s.bootAdmin, "", strings.TrimPrefix(credential, "ri-")} {
		if code, _ := scopedCall(t, s, "/v1/runtime-sessions", other, map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": "native"}); code != 401 {
			t.Fatal("wrong enrollment credential", code)
		}
	}
	for _, raw := range []string{`{}`, `{"schema_version":"local-runtime-session-enroll/v1","session_id":null}`, `{"schema_version":"local-runtime-session-enroll/v1","Session_ID":"native"}`, `{"schema_version":"local-runtime-session-enroll/v1","session_id":"a","session_id":"b"}`, `{"schema_version":"local-runtime-session-enroll/v1","session_id":"a","agent_id":"forged"}`, `{"schema_version":"local-runtime-session-enroll/v1","session_id":"a"} {}`, strings.Repeat(" ", 16385)} {
		if code, _ := scopedCall(t, s, "/v1/runtime-sessions", credential, raw); code != 400 {
			t.Fatal("malformed enrollment", code)
		}
	}
	for _, raw := range []string{`{}`, `{"schema_version":"local-runtime-identity-create/v1","instance_id":null}`, `{"schema_version":"local-runtime-identity-create/v1","expected_grant_revision":null}`, strings.Repeat(" ", 16385)} {
		if code, _ := call(t, s, "POST", "/v1/runtime-identities", token, raw); code != 400 {
			t.Fatal("malformed issuance", code)
		}
	}
	for _, path := range []string{"/v1/runtime-identities", "/v1/intents", "/v1/config", "/v1/adapter/install", "/v1/hold/fake"} {
		if code, _ := scopedCall(t, s, path, credential, map[string]any{}); code != 401 {
			t.Fatal("instance credential became admin", path, code)
		}
	}
	request := loopbackRequest("POST", "/v1/runtime-sessions", map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": "native"})
	request.Header.Set("Authorization", credential)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, request)
	if w.Code != 401 {
		t.Fatal("accepted missing Bearer")
	}
}
func TestDecisionIdentityAliasesCannotBypassReservedSubjects(t *testing.T) {
	s, _, credential, agent := managedIdentityFixture(t, "block")
	for _, key := range []string{"Agent_ID", "AGENT_ID", "agent_ID"} {
		raw := `{"platform":"hermes","session_id":"native","agent_id":"legacy","` + key + `":"` + agent + `","tool":"read_file","params":{}}`
		for _, cred := range []string{token, credential} {
			if code, _ := scopedCall(t, s, "/v1/decide", cred, raw); code != 400 {
				t.Fatal("case alias accepted", code)
			}
		}
	}
	for _, raw := range []string{`{"platform":"hermes","agent_id":"legacy","agent_id":"hri-forged"}`, `{"platform":"hermes","platform":"openclaw"}`, `{"session_id":"a","session_id":"b"}`} {
		if code, _ := scopedCall(t, s, "/v1/decide", token, raw); code != 400 {
			t.Fatal("duplicate identity accepted", code)
		}
	}
}

func TestRuntimeIdentityHTTPContractFixtures(t *testing.T) {
	s, issued, credential, _ := managedIdentityFixture(t, "block")
	actualID := issued["identity"].(map[string]any)["identity_id"].(string)
	code, list := call(t, s, "GET", "/v1/runtime-identities", token, nil)
	if code != 200 {
		t.Fatal(list)
	}
	code, enrolled := scopedCall(t, s, "/v1/runtime-sessions", credential, map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": "native-fixture"})
	if code != 200 {
		t.Fatal(enrolled)
	}
	revoke := map[string]any{"schema_version": "local-runtime-identity-revoke/v1", "actor_id": "operator"}
	code, revoked := call(t, s, "POST", "/v1/runtime-identities/"+actualID+"/revoke", token, revoke)
	if code != 200 {
		t.Fatal(revoked)
	}
	// Only nondeterministic fixture identity, path, digest and timestamps are
	// normalized. The preceding requests exercised actual issuance and binding.
	id := "ri-" + strings.Repeat("3", 32)
	agent := "hri-" + strings.Repeat("1", 32)
	normalize := func(row map[string]any) {
		row["identity_id"] = id
		row["instance_id"] = "hi-" + strings.Repeat("1", 32)
		row["agent_id"] = agent
		row["created_at"] = "2026-09-10T00:00:00Z"
		row["grant_ref"] = map[string]any{"grant_id": "grt-runtime-fixture", "admission_id": "adm-runtime-fixture", "permission_digest": strings.Repeat("a", 64)}
	}
	normalize(issued["identity"].(map[string]any))
	normalize(list["items"].([]any)[0].(map[string]any))
	issued["credential_path"] = "/fixture/state/runtime-identity-secrets/" + id + ".token"
	enrolled["identity_id"] = id
	enrolled["agent_id"] = agent
	enrolled["binding_id"] = "bind-" + strings.Repeat("d", 64)
	enrolled["intent_id"] = "int-ri-" + strings.Repeat("e", 64)
	enrolled["expires_at"] = "2026-09-10T08:00:00Z"
	revoked["identity_id"] = id
	for name, out := range map[string]any{"local-runtime-identity-issued": issued, "local-runtime-identities": list, "local-runtime-session-enrolled": enrolled, "local-runtime-identity-revoke": revoke, "local-runtime-identity-revoked": revoked} {
		b, err := json.MarshalIndent(out, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		b = append(b, '\n')
		path := "../../testdata/contracts/" + name + ".json"
		if os.Getenv("SIQ_UPDATE_RUNTIME_IDENTITY_HTTP_FIXTURES") == "1" {
			if err = os.WriteFile(path, b, 0600); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil || string(expected) != string(b) {
			t.Fatalf("contract %s differs: %v", name, err)
		}
	}
}
