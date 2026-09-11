package server

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

func updateCommitHTTPFixture(t *testing.T) (*Server, skillinstall.UpdateCommitRequest, string) {
	t.Helper()
	s, compare, route, oldID := updateHTTPFixture(t)
	code, old := call(t, s, "GET", "/v1/grants/"+oldID, token, nil)
	if code != 200 {
		t.Fatal(code, old)
	}
	candidateRoute := "/v1/grants/" + compare.CandidateGrantID
	code, challenge := call(t, s, "POST", candidateRoute+"/challenge", token, map[string]any{"expected_revision": compare.ExpectedCandidateRevision, "actor_id": "fixture-human"})
	if code != 200 {
		t.Fatal(code, challenge)
	}
	ch := challenge["challenge"].(map[string]any)
	code, approved := call(t, s, "POST", candidateRoute+"/approve", token, map[string]any{"expected_revision": compare.ExpectedCandidateRevision, "actor_id": "fixture-human", "challenge_id": ch["challenge_id"], "nonce": ch["nonce"]})
	if code != 200 {
		t.Fatal(code, approved)
	}
	req := skillinstall.UpdateStageRequest{SchemaVersion: "local-skill-update-stage-create/v1", RequestID: "up-" + strings.Repeat("a", 32), OperationSignature: compare.OperationSignature, CandidateGrantID: compare.CandidateGrantID, ExpectedCandidateRevision: int(approved["state_revision"].(float64)), ExpectedPreviousRevision: int(old["state_revision"].(float64)), ActorID: "fixture-human"}
	code, created := call(t, s, "POST", strings.TrimSuffix(route, "/update-comparison")+"/update-plans", token, req)
	if code != 201 {
		t.Fatal(code, created)
	}
	p := created["plan"].(map[string]any)
	return s, skillinstall.UpdateCommitRequest{SchemaVersion: "local-skill-update-commit/v1", UpdateID: p["update_id"].(string), PlanSignature: p["signature"].(string), ActorID: req.ActorID, ConfirmUpdate: true}, oldID
}
func TestSkillUpdateTransactionHTTPConfirmationIsolationAndReadback(t *testing.T) {
	s, req, oldID := updateCommitHTTPFixture(t)
	route := "/v1/skill-installations/updates"
	readRoute := route + "/" + req.UpdateID
	for _, entry := range []struct {
		method, path string
		body         any
	}{{"POST", route, req}, {"GET", readRoute, nil}, {"POST", readRoute + "/recover", nil}} {
		for _, credential := range []string{"", token} {
			r := loopbackRequest(entry.method, entry.path, entry.body)
			if credential != "" {
				r.Header.Set("Authorization", "Bearer "+credential)
			}
			w := httptest.NewRecorder()
			s.Handler().ServeHTTP(w, r)
			expected := 401
			if credential != "" {
				expected = 403
			}
			if w.Code != expected {
				t.Fatal(entry.path, w.Code)
			}
		}
	}
	if code, _ := call(t, s, "GET", readRoute, token, nil); code != 404 {
		t.Fatal("preparation mistaken for commit", code)
	}
	raw, _ := json.Marshal(req)
	for _, body := range []string{`{}`, strings.Replace(string(raw), `"confirm_update":true`, `"confirm_update":null`, 1), strings.TrimSuffix(string(raw), "}") + `,"target_path":"/escape"}`} {
		r := loopbackRequest("POST", route, body)
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 400 {
			t.Fatal("strict commit", w.Code)
		}
	}
	no := req
	no.ConfirmUpdate = false
	if code, _ := call(t, s, "POST", route, token, no); code != 400 {
		t.Fatal("missing confirmation accepted", code)
	}
	code, out := call(t, s, "POST", route, token, req)
	if code != 200 || out["status"] != "updated_unverified" {
		t.Fatal(code, out)
	}
	var v skillinstall.UpdateView
	raw, _ = json.Marshal(out)
	if err := json.Unmarshal(raw, &v); err != nil {
		t.Fatal(err)
	}
	if v.Result == nil || v.Result.RuntimeVerified || v.Removal.Status != "removed" || v.Installation.Status != "installed_unverified" {
		t.Fatal(v)
	}
	code, again := call(t, s, "POST", route, token, req)
	if code != 200 || again["result"].(map[string]any)["signature"] != v.Result.Signature {
		t.Fatal(code, again)
	}
	r := loopbackRequest("GET", readRoute, nil)
	r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	if w.Code != 200 || w.Header().Get("Cache-Control") != "no-store" {
		t.Fatal(w.Code)
	}
	recover := skillinstall.UpdateRecoverRequest{SchemaVersion: "local-skill-update-recover/v1", UpdateID: req.UpdateID, ClaimSignature: v.Claim.Signature, ActorID: req.ActorID, ConfirmRecovery: true}
	wrong := recover
	wrong.UpdateID = "sup-" + strings.Repeat("0", 64)
	if code, _ := call(t, s, "POST", readRoute+"/recover", token, wrong); code != 400 {
		t.Fatal("path/body mismatch", code)
	}
	wrong = recover
	wrong.ActorID = "other"
	if code, _ := call(t, s, "POST", readRoute+"/recover", token, wrong); code != 409 {
		t.Fatal("recovery actor replaced", code)
	}
	code, out = call(t, s, "POST", readRoute+"/recover", token, recover)
	if code != 200 || out["status"] != "updated_unverified" {
		t.Fatal("recovery uninstalled successful update", code, out)
	}
	for _, entry := range []struct{ method, path string }{{"GET", route}, {"POST", readRoute}, {"GET", readRoute + "/recover"}} {
		if code, _ := call(t, s, entry.method, entry.path, token, nil); code != 405 {
			t.Fatal(entry, code)
		}
	}
	g, _, err := s.d.Store.GetGrantWithSeq(oldID)
	if err != nil || g.Status != "revoked" {
		t.Fatal("old authority remains", err)
	}
	p := v.Claim.ReplacementPlan
	if code, _ := call(t, s, "POST", "/v1/skill-installations/apply", token, skillinstall.ApplyRequest{SchemaVersion: "local-skill-install-apply/v1", PlanID: p.PlanID, PlanSignature: p.Signature, ActorID: p.ActorID, ConfirmInstall: true}); code != 409 {
		t.Fatal("ordinary apply bypass", code)
	}
}

func TestSkillUpdateTransactionHTTPFailedCommitCanBeReadAndAborted(t *testing.T) {
	s, req, oldID := updateCommitHTTPFixture(t)
	// Existing private stage capacity prevents candidate preparation after the
	// declaration, exercising durable recovery without touching platform files.
	for i := 0; i < 63; i++ {
		path := filepath.Join(s.d.Store.Dir, "skill-installations", "stages", fmt.Sprintf("sip-%064x", i))
		if err := os.Mkdir(path, 0700); err != nil {
			t.Fatal(err)
		}
	}
	route := "/v1/skill-installations/updates"
	readRoute := route + "/" + req.UpdateID
	code, out := call(t, s, "POST", route, token, req)
	if code != 413 || out["error"] != "skill_install_limit" {
		t.Fatal(code, out)
	}
	code, out = call(t, s, "GET", readRoute, token, nil)
	if code != 200 || out["status"] != "confirmed" {
		t.Fatal(code, out)
	}
	claim := out["claim"].(map[string]any)
	recover := skillinstall.UpdateRecoverRequest{SchemaVersion: "local-skill-update-recover/v1", UpdateID: req.UpdateID, ClaimSignature: claim["signature"].(string), ActorID: req.ActorID, ConfirmRecovery: true}
	bad := recover
	bad.ConfirmRecovery = false
	if code, _ := call(t, s, "POST", readRoute+"/recover", token, bad); code != 400 {
		t.Fatal("unconfirmed recovery", code)
	}
	code, out = call(t, s, "POST", readRoute+"/recover", token, recover)
	if code != 200 || out["status"] != "aborted" {
		t.Fatal(code, out)
	}
	g, _, err := s.d.Store.GetGrantWithSeq(oldID)
	if err != nil || g.Status != "approved" {
		t.Fatal("aborting before removal revoked old", err)
	}
	code, out = call(t, s, "POST", route, token, req)
	if code != 200 || out["status"] != "aborted" {
		t.Fatal("aborted request restarted", code, out)
	}
}
