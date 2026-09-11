package server

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func resourceRequest(t *testing.T, revision int) map[string]any {
	t.Helper()
	raw, err := os.ReadFile("../../testdata/contracts/grant-resource-edit.json")
	if err != nil {
		t.Fatal(err)
	}
	var body map[string]any
	if err := json.Unmarshal(raw, &body); err != nil {
		t.Fatal(err)
	}
	body["expected_revision"] = revision
	return body
}

func TestGrantResourcesHTTPContractAuthorizationRevisionAndAudit(t *testing.T) {
	s, store, gid, rev := expiryFixture(t)
	route := "/v1/grants/" + gid
	body := resourceRequest(t, rev)
	before, _, _ := store.GetGrantWithSeq(gid)
	_, issued := call(t, s, "POST", route+"/challenge", token, withRevision(map[string]any{}, rev))
	ch := issued["challenge"].(map[string]any)
	for _, credential := range []string{"", token} {
		req := loopbackRequest("POST", route+"/resources", body)
		if credential != "" {
			req.Header.Set("Authorization", "Bearer "+credential)
		}
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, req)
		if w.Code != 401 && w.Code != 403 {
			t.Fatal("non-admin changed resources", w.Code)
		}
	}
	code, out := call(t, s, "POST", route+"/resources", token, body)
	if code != 200 {
		t.Fatal(code, out)
	}
	g, seq, err := store.GetGrantWithSeq(gid)
	if err != nil || seq != rev+1 || stateRevision(t, out) != seq || g.Subject != before.Subject || g.AdmissionID != before.AdmissionID || g.Status != "pending_approval" || !grant.Verify(s.d.Key.Public(), *g) {
		t.Fatal("invalid committed result", err)
	}
	if code, _ := call(t, s, "POST", route+"/resources", token, body); code != 409 {
		t.Fatal("stale edit accepted")
	}
	if code, _ := call(t, s, "POST", route+"/approve", token, map[string]any{"expected_revision": seq, "actor_id": "operator", "challenge_id": ch["challenge_id"], "nonce": ch["nonce"]}); code != 400 {
		t.Fatal("old challenge survived")
	}
	body["expected_revision"] = seq
	body["tools"], body["network"], body["models"] = []string{}, []any{}, []string{}
	body["filesystem"] = map[string]any{"read_only": []string{}, "read_write": []string{}}
	if code, out := call(t, s, "POST", route+"/resources", token, body); code != 200 {
		t.Fatal(code, out)
	}
	g, seq, _ = store.GetGrantWithSeq(gid)
	for _, f := range g.Facts {
		if f.Effect == "allow" && (f.Domain == "tool" || f.Domain == "filesystem" || f.Domain == "network" || f.Domain == "model") {
			t.Fatal("clear kept old allow")
		}
	}
	code, out = approveChallenged(t, s, gid, "operator", seq)
	if code != 200 {
		t.Fatal(out)
	}
	body["expected_revision"] = stateRevision(t, out)
	if code, _ := call(t, s, "POST", route+"/resources", token, body); code != 409 {
		t.Fatal("edited approved grant", code)
	}
	events, err := store.TailAudit(100)
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, ev := range events {
		if ev.Event == "grant_resources" && ev.Target == gid && ev.ActorID == "fixture-operator" {
			count++
		}
	}
	if count != 2 {
		t.Fatal("missing successful-edit audit", count)
	}
}

func TestGrantResourcesHTTPStrictInputDoesNotMutate(t *testing.T) {
	s, store, gid, rev := expiryFixture(t)
	route := "/v1/grants/" + gid + "/resources"
	for _, field := range []string{"schema_version", "expected_revision", "actor_id", "tools", "network", "filesystem", "models"} {
		for _, missing := range []bool{false, true} {
			body := resourceRequest(t, rev)
			if missing {
				delete(body, field)
			} else {
				body[field] = nil
			}
			if code, out := call(t, s, "POST", route, token, body); code != 400 {
				t.Fatal(field, missing, code, out)
			}
		}
	}
	for _, change := range []map[string]any{
		{"actor_id": " "}, {"actor_id": strings.Repeat("人", 129)}, {"expected_revision": -1}, {"expected_revision": 0.5}, {"subject_id": "other"}, {"status": "effective"}, {"tools": []string{"*"}}, {"filesystem": map[string]any{"read_only": []string{}}}, {"filesystem": map[string]any{"read_only": []string{}, "read_write": []string{}, "escape": true}}, {"network": []any{map[string]any{"endpoint": "example.test:443", "effect": "allow", "escape": true}}},
	} {
		body := resourceRequest(t, rev)
		for k, v := range change {
			body[k] = v
		}
		if code, out := call(t, s, "POST", route, token, body); code != 400 {
			t.Fatal(change, code, out)
		}
	}
	raw, _ := json.Marshal(resourceRequest(t, rev))
	for _, body := range []string{string(raw) + " {}", string(raw) + strings.Repeat(" ", 64<<10), "{", "[]"} {
		if code, out := call(t, s, "POST", route, token, body); code != 400 {
			t.Fatal("malformed body accepted", code, out)
		}
	}
	_, seq, err := store.GetGrantWithSeq(gid)
	if err != nil || seq != rev {
		t.Fatal("rejected input changed state", err)
	}
	if code, _ := call(t, s, "POST", "/v1/grants/missing/resources", token, nil); code != 404 {
		t.Fatal(code)
	}
}

func TestGrantResourcesAuditFailureDoesNotPublish(t *testing.T) {
	s, store, gid, rev := expiryFixture(t)
	if err := os.MkdirAll(filepath.Join(store.Dir, "commit-audit", fmt.Sprintf("%s.%d.json", gid, rev+1)), 0700); err != nil {
		t.Fatal(err)
	}
	if code, out := call(t, s, "POST", "/v1/grants/"+gid+"/resources", token, resourceRequest(t, rev)); code != 500 || out["error"] != "incomplete_commit" {
		t.Fatal(code, out)
	}
	if _, _, err := store.GetGrantWithSeq(gid); err == nil {
		t.Fatal("unaudited authority exposed")
	}
}

func TestEditedResourcesReachRuntimeAfterApproval(t *testing.T) {
	s, _, gid, rev := expiryFixture(t)
	route := "/v1/grants/" + gid
	code, edited := call(t, s, "POST", route+"/resources", token, resourceRequest(t, rev))
	if code != 200 {
		t.Fatal(edited)
	}
	code, approved := approveChallenged(t, s, gid, "operator", stateRevision(t, edited))
	if code != 200 {
		t.Fatal(approved)
	}
	if code, out := call(t, s, "POST", route+"/deploy", token, withRevision(map[string]any{}, stateRevision(t, approved))); code != 200 {
		t.Fatal(out)
	}
	for _, tc := range []struct{ name, tool, key, value, action string }{
		{"readonly allows read", "read_file", "path", "/work/reports with spaces,commas/report", "allow"},
		{"readonly blocks write", "write_file", "path", "/work/reports with spaces,commas/report", "deny"},
		{"readwrite allows write", "write_file", "path", "/work/output/report", "allow"},
		{"outside denied", "read_file", "path", "/elsewhere/report", "deny"},
		{"exact endpoint", "web_fetch", "url", "https://api.example.test/report", "allow"},
		{"wrong port", "web_fetch", "url", "https://api.example.test:8443/report", "deny"},
		{"denied endpoint", "web_fetch", "url", "https://private.example.test/report", "deny"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			code, out := call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "hermes", "session_id": "resource-edit-fixture-" + tc.name, "agent_id": "expiry-agent", "tool": tc.tool, "params": map[string]any{tc.key: tc.value}})
			if code != 200 || out["action"] != tc.action {
				t.Fatal(code, out)
			}
		})
	}
}
