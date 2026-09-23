package server

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/decisionrelay"
)

func selfCall(t *testing.T, s *Server, method, path, credential string, body any) (int, map[string]any) {
	t.Helper()
	r := loopbackRequest(method, path, body)
	r.Header.Set("Authorization", "Bearer "+credential)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	out := map[string]any{}
	_ = json.Unmarshal(w.Body.Bytes(), &out)
	if w.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("cacheable self identity")
	}
	return w.Code, out
}

func TestRuntimeIdentitySelfHTTP(t *testing.T) {
	s, issued, credential, agent := managedIdentityFixture(t, "block")
	identity := issued["identity"].(map[string]any)
	code, self := selfCall(t, s, "GET", "/v1/runtime-identity/self", credential, nil)
	if code != 200 || self["identity_id"] != identity["identity_id"] || self["agent_id"] != agent || !reflect.DeepEqual(self["grant_ref"], identity["grant_ref"]) {
		t.Fatal(code, self)
	}
	raw, _ := json.Marshal(self)
	for _, word := range []string{credential, "credential", "signature", "actor_id", "created_at"} {
		if bytes.Contains(raw, []byte(word)) {
			t.Fatal("private field leaked")
		}
	}
	body := map[string]any{"schema_version": "local-runtime-identity-self-revoke/v1"}
	code, rev := selfCall(t, s, "POST", "/v1/runtime-identity/self/revoke", credential, body)
	if code != 200 || rev["revoked"] != true || rev["identity_id"] != identity["identity_id"] {
		t.Fatal(code, rev)
	}
	code, retry := selfCall(t, s, "POST", "/v1/runtime-identity/self/revoke", credential, body)
	if code != 200 || !reflect.DeepEqual(rev, retry) {
		t.Fatal("cleanup retry failed", code)
	}
	if code, _ = selfCall(t, s, "GET", "/v1/runtime-identity/self", credential, nil); code != 401 {
		t.Fatal("revoked identity active", code)
	}
	if code, _ = scopedCall(t, s, "/v1/runtime-sessions", credential, map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": "native"}); code != 401 {
		t.Fatal("self revocation bypass", code)
	}
	// Shared, normalized wire samples are also consumed by Python JSON Schema.
	self["identity_id"] = "ri-" + strings.Repeat("3", 32)
	self["instance_id"] = "hi-" + strings.Repeat("1", 32)
	self["agent_id"] = "hri-" + strings.Repeat("1", 32)
	self["grant_ref"] = map[string]any{"grant_id": "grt-runtime-fixture", "admission_id": "adm-runtime-fixture", "permission_digest": strings.Repeat("a", 64)}
	for name, value := range map[string]any{"local-runtime-identity-self": self, "local-runtime-identity-self-revoke": body} {
		b, err := os.ReadFile("../../testdata/contracts/" + name + ".json")
		if err != nil {
			t.Fatal(err)
		}
		var fixture map[string]any
		if json.Unmarshal(b, &fixture) != nil || !reflect.DeepEqual(fixture, value) {
			t.Fatal("shared sample differs", name)
		}
	}
}

func TestRuntimeIdentitySelfHTTPRejectsForgedAndManagementCredentials(t *testing.T) {
	s, _, credential, _ := managedIdentityFixture(t, "block")
	body := map[string]any{"schema_version": "local-runtime-identity-self-revoke/v1"}
	for _, other := range []string{"", token, s.bootAdmin, credential[:36] + strings.Repeat("0", 64), "ri-" + strings.Repeat("f", 32) + credential[35:]} {
		if code, _ := selfCall(t, s, "GET", "/v1/runtime-identity/self", other, nil); code != 401 {
			t.Fatal("wrong self credential", code)
		}
		if code, _ := selfCall(t, s, "POST", "/v1/runtime-identity/self/revoke", other, body); code != 401 {
			t.Fatal("wrong cleanup credential", code)
		}
	}
	if code, _ := selfCall(t, s, "GET", "/v1/runtime-identity/self", credential, nil); code != 200 {
		t.Fatal("invalid callers revoked real identity")
	}
}

func TestRuntimeIdentitySelfHTTPStrictShape(t *testing.T) {
	s, _, credential, _ := managedIdentityFixture(t, "block")
	for _, body := range []string{`{}`, `{"schema_version":null}`, `{"schema_version":"local-runtime-identity-self-revoke/v1","actor_id":"admin"}`, `{"schema_version":"local-runtime-identity-self-revoke/v1","identity_id":"other"}`, `{"schema_version":"local-runtime-identity-self-revoke/v1","schema_version":"local-runtime-identity-self-revoke/v1"}`, `{"Schema_Version":"local-runtime-identity-self-revoke/v1"}`, `{"schema_version":"local-runtime-identity-self-revoke/v1"} {}`, strings.Repeat(" ", 16385)} {
		if code, _ := selfCall(t, s, "POST", "/v1/runtime-identity/self/revoke", credential, body); code != 400 {
			t.Fatal("bad cleanup body", code)
		}
	}
	for _, path := range []string{"/v1/runtime-identity/self?", "/v1/runtime-identity/self?identity_id=other", "/v1/runtime-identity/%73elf"} {
		if code, _ := selfCall(t, s, "GET", path, credential, nil); code != 400 {
			t.Fatal("noncanonical request", code)
		}
	}
	if code, _ := selfCall(t, s, "GET", "/v1/runtime-identity/self", credential, map[string]any{}); code != 400 {
		t.Fatal("GET body accepted")
	}
	if code, _ := selfCall(t, s, "POST", "/v1/runtime-identity/self", credential, nil); code != 405 {
		t.Fatal("wrong method accepted")
	}
	r := loopbackRequest("GET", "/v1/runtime-identity/self", nil)
	r.Header.Add("Authorization", "Bearer "+credential)
	r.Header.Add("Authorization", "Bearer "+credential)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	if w.Code != 401 {
		t.Fatal("ambiguous bearer accepted")
	}
	if code, _ := selfCall(t, s, "GET", "/v1/runtime-identity/self", credential, nil); code != 200 {
		t.Fatal("bad input had side effects")
	}
}

func TestRuntimeIdentitySelfHTTPPersistenceFailure(t *testing.T) {
	s, issued, credential, _ := managedIdentityFixture(t, "block")
	id := issued["identity"].(map[string]any)["identity_id"].(string)
	if err := os.WriteFile(filepath.Join(s.d.Store.Dir, "runtime-identity-revocations", id+".json"), []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	code, out := selfCall(t, s, "POST", "/v1/runtime-identity/self/revoke", credential, map[string]any{"schema_version": "local-runtime-identity-self-revoke/v1"})
	if code != 503 || out["revoked"] == true {
		t.Fatal("unconfirmed cleanup reported success", code)
	}
}

func TestRuntimeIdentitySelfRoutesRemainHiddenFromRelay(t *testing.T) {
	s, issued, credential, agent := managedIdentityFixture(t, "block")
	id := issued["identity"].(map[string]any)
	transport := &relayServerTransport{handler: s.Handler()}
	cfg := relayConfig(id["identity_id"].(string), id["instance_id"].(string), agent, "siq:openshell:pool:"+strings.Repeat("2", 24)+":run-001:siq_analysis")
	for _, version := range []string{decisionrelay.SchemaVersion, decisionrelay.CandidateSchemaVersion, decisionrelay.IsolatedSchemaVersion} {
		cfg.SchemaVersion = version
		if version != decisionrelay.SchemaVersion {
			cfg.Binding.SandboxNamespace = "siq-openshell-scope-validation"
			cfg.Binding.SandboxName = "siq-qwen38-scoped-0123456789abcdef"
		}
		if version == decisionrelay.IsolatedSchemaVersion {
			cfg.Upstream = decisionrelay.IsolatedLoopbackURL
		}
		relay, err := decisionrelay.NewWithClient(cfg, &http.Client{Transport: transport})
		if err != nil {
			t.Fatal(err)
		}
		for _, path := range []string{"/v1/runtime-identity/self", "/v1/runtime-identity/self/revoke", "/v1/runtime-request-issuers", "/v1/runtime-identity/self/requests", "/v1/runtime-identity/self/requests/cancel"} {
			before := transport.calls
			if code, _ := relayCall(t, relay, path, credential, map[string]any{"schema_version": "local-runtime-identity-self-revoke/v1"}); code != 404 || transport.calls != before {
				t.Fatal("host cleanup route exposed", code)
			}
		}
	}
}
