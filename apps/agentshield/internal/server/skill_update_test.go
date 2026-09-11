package server

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

func updateHTTPFixture(t *testing.T) (*Server, skillinstall.UpdateCompareRequest, string, string) {
	t.Helper()
	s, apply, grantID := appliedHTTPFixture(t, true)
	code, installed := call(t, s, "POST", "/v1/skill-installations/apply", token, apply)
	if code != 200 {
		t.Fatal(code, installed)
	}
	plan := installed["plan"].(map[string]any)
	source := t.TempDir()
	if err := os.WriteFile(filepath.Join(source, "SKILL.md"), []byte("---\nname: example\ndescription: Read the next report.\nallowed-tools: read_file write_file\n---\nNext report.\n"), 0600); err != nil {
		t.Fatal(err)
	}
	code, imported := call(t, s, "POST", "/v1/skill-imports", token, map[string]any{"schema_version": "local-skill-import-create/v1", "import_id": "si-" + strings.Repeat("e", 32), "source_kind": "local_dir", "path": source, "actor_id": "fixture-human"})
	if code != 201 {
		t.Fatal(code, imported)
	}
	candidate := imported["import"].(map[string]any)
	code, permission := call(t, s, "POST", "/v1/skill-imports/"+candidate["import_id"].(string)+"/permissions", token, map[string]any{"schema_version": "local-skill-import-permission-create/v1", "request_id": "ip-" + strings.Repeat("f", 32), "artifact_digest": candidate["artifact_digest"], "analysis_sha256": candidate["analysis_sha256"], "instance_id": plan["instance_id"], "actor_id": "fixture-human"})
	if code != 201 {
		t.Fatal(code, permission)
	}
	req := skillinstall.UpdateCompareRequest{SchemaVersion: "local-skill-update-compare/v1", OperationSignature: installed["operation"].(map[string]any)["signature"].(string), CandidateGrantID: permission["grant"].(map[string]any)["grant_id"].(string), ExpectedCandidateRevision: int(permission["state_revision"].(float64))}
	route := "/v1/skill-installations/operations/" + installed["install_id"].(string) + "/update-comparison"
	return s, req, route, grantID
}
func TestSkillUpdateComparisonHTTPReadOnlyAndCapability(t *testing.T) {
	s, req, route, grantID := updateHTTPFixture(t)
	for _, credential := range []string{"", token} {
		r := loopbackRequest("POST", route, req)
		if credential != "" {
			r.Header.Set("Authorization", "Bearer "+credential)
		}
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		want := 401
		if credential != "" {
			want = 403
		}
		if w.Code != want {
			t.Fatal("comparison capability", w.Code)
		}
	}
	if code, _ := call(t, s, "GET", route, token, nil); code != 405 {
		t.Fatal("comparison method", code)
	}
	raw, _ := json.Marshal(req)
	for _, bad := range []string{`{}`, strings.Replace(string(raw), `"expected_candidate_revision":0`, `"expected_candidate_revision":null`, 1), strings.Replace(string(raw), `"candidate_grant_id":`, `"candidate_grant_id":"duplicate","candidate_grant_id":`, 1), strings.TrimSuffix(string(raw), "}") + `,"confirm_update":true}`} {
		r := loopbackRequest("POST", route, bad)
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 400 {
			t.Fatal("comparison strict request", w.Code, w.Body.String())
		}
	}
	r := loopbackRequest("POST", route, req)
	r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	if w.Code != 200 || w.Header().Get("Cache-Control") != "no-store" {
		t.Fatal(w.Code, w.Body.String())
	}
	var comparison skillinstall.UpdateComparison
	if err := json.Unmarshal(w.Body.Bytes(), &comparison); err != nil || comparison.PlatformChanges || comparison.RuntimeVerified || !comparison.RequiresConfirmation || comparison.ContentChangesTotal == 0 || comparison.CandidateGrant.Status == "approved" {
		t.Fatal("comparison changed approval", err)
	}
	current, _, err := s.d.Store.GetGrantWithSeq(grantID)
	if err != nil || current.Status != "approved" {
		t.Fatal("old grant changed", err)
	}
	if code, out := call(t, s, "GET", strings.TrimSuffix(route, "/update-comparison")+"/removal", token, nil); code != 200 || out["status"] != "not_requested" {
		t.Fatal("comparison started removal", code, out)
	}
	req.ExpectedCandidateRevision++
	if code, _ := call(t, s, "POST", route, token, req); code != 409 {
		t.Fatal("stale candidate accepted", code)
	}
}

func TestSkillUpdatePlanHTTPApprovalRetryReadAndIsolation(t *testing.T) {
	s, compare, comparisonRoute, oldGrantID := updateHTTPFixture(t)
	originalRoute := strings.TrimSuffix(comparisonRoute, "/update-comparison")
	createRoute := originalRoute + "/update-plans"
	code, old := call(t, s, "GET", "/v1/grants/"+oldGrantID, token, nil)
	if code != 200 {
		t.Fatal(code, old)
	}
	req := skillinstall.UpdateStageRequest{SchemaVersion: "local-skill-update-stage-create/v1", RequestID: "up-" + strings.Repeat("a", 32), OperationSignature: compare.OperationSignature, CandidateGrantID: compare.CandidateGrantID, ExpectedCandidateRevision: compare.ExpectedCandidateRevision, ExpectedPreviousRevision: int(old["state_revision"].(float64)), ExpectedBindingSignature: "", ActorID: "fixture-human"}
	if code, _ := call(t, s, "POST", createRoute, token, req); code != 409 {
		t.Fatal("unapproved update staged", code)
	}
	candidateRoute := "/v1/grants/" + req.CandidateGrantID
	code, challenge := call(t, s, "POST", candidateRoute+"/challenge", token, map[string]any{"expected_revision": req.ExpectedCandidateRevision, "actor_id": req.ActorID})
	if code != 200 {
		t.Fatal(code, challenge)
	}
	ch := challenge["challenge"].(map[string]any)
	code, approved := call(t, s, "POST", candidateRoute+"/approve", token, map[string]any{"expected_revision": req.ExpectedCandidateRevision, "actor_id": req.ActorID, "challenge_id": ch["challenge_id"], "nonce": ch["nonce"]})
	if code != 200 {
		t.Fatal(code, approved)
	}
	req.ExpectedCandidateRevision = int(approved["state_revision"].(float64))
	for _, credential := range []string{"", token} {
		r := loopbackRequest("POST", createRoute, req)
		if credential != "" {
			r.Header.Set("Authorization", "Bearer "+credential)
		}
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		want := 401
		if credential != "" {
			want = 403
		}
		if w.Code != want {
			t.Fatal("update staging capability", w.Code)
		}
	}
	raw, _ := json.Marshal(req)
	for _, bad := range []string{`{}`, strings.Replace(string(raw), `"expected_binding_signature":""`, `"expected_binding_signature":null`, 1), strings.TrimSuffix(string(raw), "}") + `,"target_path":"/escape"}`} {
		r := loopbackRequest("POST", createRoute, bad)
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 400 {
			t.Fatal("stage strict body", w.Code, w.Body.String())
		}
	}
	code, created := call(t, s, "POST", createRoute, token, req)
	if code != 201 || created["reused"] != false {
		t.Fatal(code, created)
	}
	plan := created["plan"].(map[string]any)
	id := plan["update_id"].(string)
	if plan["platform_changes"] != false || plan["runtime_verified"] != false || plan["requires_confirmation"] != true {
		t.Fatal("preparation misrepresented")
	}
	code, again := call(t, s, "POST", createRoute, token, req)
	if code != 200 || again["reused"] != true || again["plan"].(map[string]any)["signature"] != plan["signature"] {
		t.Fatal("stage retry", code, again)
	}
	readRoute := "/v1/skill-installations/update-plans/" + id
	for _, credential := range []string{"", token} {
		r := loopbackRequest("GET", readRoute, nil)
		if credential != "" {
			r.Header.Set("Authorization", "Bearer "+credential)
		}
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		want := 401
		if credential != "" {
			want = 403
		}
		if w.Code != want {
			t.Fatal("stage read capability", w.Code)
		}
	}
	r := loopbackRequest("GET", readRoute, nil)
	r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	if w.Code != 200 || w.Header().Get("Cache-Control") != "no-store" {
		t.Fatal(w.Code, w.Body.String())
	}
	if code, _ := call(t, s, "POST", readRoute, token, nil); code != 405 {
		t.Fatal("update read accepted write", code)
	}
	code, current := call(t, s, "GET", "/v1/grants/"+oldGrantID, token, nil)
	if code != 200 || current["state_revision"] != old["state_revision"] || current["grant"].(map[string]any)["signature"] != old["grant"].(map[string]any)["signature"] {
		t.Fatal("update preparation changed old Grant", code, current)
	}
	if code, removal := call(t, s, "GET", originalRoute+"/removal", token, nil); code != 200 || removal["status"] != "not_requested" {
		t.Fatal("preparation removed old installation", code, removal)
	}
	path := filepath.Join(s.d.Store.Dir, "skill-installations", "update-stages", id, "payload", "SKILL.md")
	if err := os.WriteFile(path, []byte("tampered private copy"), 0600); err != nil {
		t.Fatal(err)
	}
	if code, _ := call(t, s, "GET", readRoute, token, nil); code != 409 {
		t.Fatal("corrupt stage remained ready", code)
	}
}
