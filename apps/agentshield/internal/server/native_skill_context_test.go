package server

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/skillcontext"
)

func nativeHistoryFixture(t *testing.T, f *nativeOnlineFixture) *skillcontext.InvocationContext {
	t.Helper()
	code, paired := call(t, f.server, "POST", "/v1/pair", "", map[string]any{"code": testPairingCode})
	if code != 200 {
		t.Fatal("pairing", code, paired)
	}
	f.server.bootAdmin = paired["session"].(string)
	// Explicit signed historical fixture, not a claim of native loading or live
	// installation. Producer-store tests and real business runs cover issuance.
	raw, err := os.ReadFile("../../testdata/contracts/skill-execution-context-v2.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	var c skillcontext.InvocationContext
	if err = json.Unmarshal(raw, &c); err != nil {
		t.Fatal(err)
	}
	subjectRaw, _ := json.Marshal(c.Subject)
	var subject map[string]any
	_ = json.Unmarshal(subjectRaw, &subject)
	canonical, _ := canon.Marshal(map[string]any{"domain": skillcontext.InvocationSchema, "subject": subject, "load_id": c.Loader.LoadID})
	digest := sha256.Sum256(canonical)
	c.ContextID = "sec-" + hex.EncodeToString(digest[:16])
	c.Signature, err = f.server.d.Key.SignCanonical(c.Unsigned())
	if err != nil {
		t.Fatal(err)
	}
	raw, _ = json.Marshal(c)
	if err = os.WriteFile(filepath.Join(f.server.d.Store.Dir, "skill-contexts-v2", c.ContextID+".json"), raw, 0600); err != nil {
		t.Fatal(err)
	}
	return &c
}

func nativeRevokeBody(c *skillcontext.InvocationContext) map[string]any {
	return map[string]any{"schema_version": skillcontext.InvocationRevokeRequestSchema, "expected_context_signature": c.Signature, "actor_id": "fixture-operator", "confirm_revoke": true}
}

func TestNativeContextHTTPExactRevokeAndHistory(t *testing.T) {
	f := nativeOnlineServer(t)
	c := nativeHistoryFixture(t, f)
	path := "/v2/skill-contexts/" + c.ContextID
	for _, credential := range []string{"", token, f.credential, f.publisher} {
		for _, target := range []struct {
			method, path string
			body         any
		}{{"GET", path, nil}, {"GET", "/v2/skill-contexts?install_id=ins-1", nil}, {"POST", path + "/revoke", nativeRevokeBody(c)}} {
			w := rawContextCall(f.server, target.method, target.path, credential, target.body)
			if w.Code != 401 && w.Code != 403 {
				t.Fatalf("non-admin %s: %d", target.path, w.Code)
			}
		}
	}
	f.native.failed.Store(true) // Host failure must not prevent withdrawal.
	code, got := call(t, f.server, "GET", path, f.server.bootAdmin, nil)
	if code != 200 || got["revocation"] != nil || got["context"].(map[string]any)["signature"] != c.Signature {
		t.Fatal(code, got)
	}
	wrong := nativeRevokeBody(c)
	wrong["expected_context_signature"] = strings.Repeat("0", 128)
	if code, _ = call(t, f.server, "POST", path+"/revoke", f.server.bootAdmin, wrong); code != 409 {
		t.Fatal("stale confirmation", code)
	}
	code, first := call(t, f.server, "POST", path+"/revoke", f.server.bootAdmin, nativeRevokeBody(c))
	if code != 200 || first["context_signature"] != c.Signature || first["schema_version"] != skillcontext.InvocationRevocationSchema {
		t.Fatal(code, first)
	}
	code, second := call(t, f.server, "POST", path+"/revoke", f.server.bootAdmin, nativeRevokeBody(c))
	if code != 200 || first["signature"] != second["signature"] {
		t.Fatal("retry changed tombstone", code, second)
	}
	if code, _ = call(t, f.server, "POST", path+"/revoke", f.server.bootAdmin, wrong); code != 409 {
		t.Fatal("stale retry", code)
	}
	code, page := call(t, f.server, "GET", "/v2/skill-contexts?install_id=ins-1&session_id=s1&limit=1", f.server.bootAdmin, nil)
	if code != 200 || len(page["contexts"].([]any)) != 1 || page["next_after"] != "" {
		t.Fatal(code, page)
	}
	row := page["contexts"].([]any)[0].(map[string]any)
	if row["revocation"].(map[string]any)["signature"] != first["signature"] {
		t.Fatal("missing tombstone")
	}
	if code, _ = call(t, f.server, "GET", "/v1/skill-contexts/"+c.ContextID, f.server.bootAdmin, nil); code == 200 {
		t.Fatal("v1 mixed native context")
	}
	if code, _ = call(t, f.server, "GET", "/v2/skill-contexts/sec-"+strings.Repeat("f", 32), f.server.bootAdmin, nil); code != 404 {
		t.Fatal(code)
	}
}

func TestNativeContextHTTPRejectsMalformedAndAuditFailure(t *testing.T) {
	f := nativeOnlineServer(t)
	c := nativeHistoryFixture(t, f)
	path := "/v2/skill-contexts/" + c.ContextID
	for _, q := range []string{"", "?install_id=ins-1&install_id=ins-2", "?install_id=ins-1&limit=65", "?install_id=ins-1&limit=01", "?install_id=ins-1&limit=+1", "?install_id=ins-1&session_id=", "?install_id=ins-1&after=invalid", "?install_id=ins-1&extra=true", "?install_id=ins-1&session_id=%00"} {
		if code, _ := call(t, f.server, "GET", "/v2/skill-contexts"+q, f.server.bootAdmin, nil); code != 400 {
			t.Fatal(q, code)
		}
	}
	for _, field := range []string{"schema_version", "confirm_revoke", "actor_id", "expected_context_signature"} {
		body := nativeRevokeBody(c)
		switch field {
		case "schema_version":
			body[field] = skillcontext.RevokeRequestSchema
		case "confirm_revoke":
			body[field] = false
		case "actor_id":
			body[field] = "\noperator"
		default:
			body[field] = "bad"
		}
		if code, _ := call(t, f.server, "POST", path+"/revoke", f.server.bootAdmin, body); code != 400 {
			t.Fatal(field, code)
		}
	}
	body := nativeRevokeBody(c)
	body["grant_id"] = "forged"
	if code, _ := call(t, f.server, "POST", path+"/revoke", f.server.bootAdmin, body); code != 400 {
		t.Fatal(code)
	}
	raw := `{"schema_version":"local-skill-execution-context-revoke/v2","schema_version":"local-skill-execution-context-revoke/v2"}`
	if w := rawContextCall(f.server, "POST", path+"/revoke", f.server.bootAdmin, raw); w.Code != 400 {
		t.Fatal(w.Code)
	}
	if code, _ := call(t, f.server, "POST", "/v2/skill-contexts", f.server.bootAdmin, nativeRevokeBody(c)); code != http.StatusMethodNotAllowed {
		t.Fatal("public issuance", code)
	}
	audit := filepath.Join(f.server.d.Store.Dir, "audit.jsonl")
	if err := os.Rename(audit, audit+".saved"); err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	if err := os.Mkdir(audit, 0700); err != nil {
		t.Fatal(err)
	}
	if code, _ := call(t, f.server, "POST", path+"/revoke", f.server.bootAdmin, nativeRevokeBody(c)); code != 500 {
		t.Fatal("audit failure", code)
	}
	if _, err := os.Lstat(filepath.Join(f.server.d.Store.Dir, "skill-context-revocations-v2", c.ContextID+".json")); !os.IsNotExist(err) {
		t.Fatal("mutation despite audit failure", err)
	}
}

func TestNativeContextHTTPMissingRuntimeStore(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, path := range []string{"/v2/skill-contexts?install_id=ins-1", "/v2/skill-contexts/sec-" + strings.Repeat("a", 32)} {
		if code, _ := call(t, s, "GET", path, s.bootAdmin, nil); code != 503 {
			t.Fatal(path, code)
		}
	}
}
