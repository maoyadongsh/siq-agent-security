package server

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func importPermissionFixture(t *testing.T) (*Server, string, importPermissionRequest) {
	t.Helper()
	s, req := skillImportHTTPFixture(t)
	s.d.HermesOS = "linux"
	rows := instanceFixture(t, s)
	if code, out := call(t, s, "POST", "/v1/skill-imports", token, req); code != 201 {
		t.Fatal(code, out)
	}
	rec, _, err := s.skillImports.Load(nil, req.ImportID)
	if err != nil {
		t.Fatal(err)
	}
	body := importPermissionRequest{SchemaVersion: "local-skill-import-permission-create/v1", RequestID: "ip-" + strings.Repeat("b", 32), ArtifactDigest: rec.ArtifactDigest, AnalysisSHA256: rec.AnalysisSHA256, InstanceID: rows[1].(map[string]any)["instance_id"].(string), ActorID: "fixture-human"}
	return s, req.ImportID, body
}
func TestImportedPermissionHTTPPrepareApproveAndRefuseEarlyDeployment(t *testing.T) {
	s, id, body := importPermissionFixture(t)
	route := "/v1/skill-imports/" + id + "/permissions"
	code, out := call(t, s, "POST", route, token, body)
	if code != 201 || out["installed"] != false || out["reused"] != false {
		t.Fatal(code, out)
	}
	raw, _ := json.Marshal(out["grant"])
	var g grant.Grant
	if json.Unmarshal(raw, &g) != nil {
		t.Fatal("grant decode")
	}
	if g.Status != "pending_approval" || g.Subject.ID != "hri-"+strings.TrimPrefix(body.InstanceID, "hi-") {
		t.Fatal("wrong target", g)
	}
	if code, out := call(t, s, "POST", route, token, body); code != 200 || out["reused"] != true {
		t.Fatal(code, out)
	}
	action := "/v1/grants/" + g.GrantID
	code, ch := call(t, s, "POST", action+"/challenge", token, map[string]any{"expected_revision": 0, "actor_id": body.ActorID})
	if code != 200 {
		t.Fatal(code, ch)
	}
	challenge := ch["challenge"].(map[string]any)
	approve := map[string]any{"expected_revision": 0, "actor_id": body.ActorID, "challenge_id": challenge["challenge_id"], "nonce": challenge["nonce"]}
	code, out = call(t, s, "POST", action+"/approve", token, approve)
	if code != 200 {
		t.Fatal(code, out)
	}
	code, out = call(t, s, "POST", action+"/deploy", token, map[string]any{"expected_revision": 1, "actor_id": body.ActorID})
	if code < 400 || out["error"] != "grant_import_installation_required" {
		t.Fatal("early deploy", code, out)
	}
	code, out = call(t, s, "POST", route, token, body)
	if code != 200 || out["grant"].(map[string]any)["status"] != "approved" {
		t.Fatal("retry reset approved grant", code, out)
	}
	// Replacing a snapshot invalidates source-bound approval operations, while revoke stays available.
	if err := os.WriteFile(filepath.Join(s.d.Store.Dir, "skill-imports", "blobs", id, "payload", "SKILL.md"), []byte("changed"), 0600); err != nil {
		t.Fatal(err)
	}
	if code, _ := call(t, s, "POST", action+"/challenge", token, map[string]any{"expected_revision": 1, "actor_id": body.ActorID}); code != 409 {
		t.Fatal("changed source challenged", code)
	}
	if code, _ := call(t, s, "POST", route, token, body); code != 409 {
		t.Fatal("changed source reused", code)
	}
	if code, out := call(t, s, "POST", action+"/revoke", token, map[string]any{"expected_revision": 1, "actor_id": body.ActorID}); code != 200 {
		t.Fatal("damaged source cannot revoke", code, out)
	}
}
func TestImportedPermissionHTTPAdminAndSourceTargetValidation(t *testing.T) {
	s, id, body := importPermissionFixture(t)
	route := "/v1/skill-imports/" + id + "/permissions"
	for _, credential := range []string{"", token} {
		r := loopbackRequest("POST", route, body)
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
			t.Fatal(w.Code)
		}
	}
	for _, kind := range []string{"digest", "analysis", "target", "actor", "request", "schema"} {
		bad := body
		want := 400
		switch kind {
		case "digest":
			bad.ArtifactDigest = strings.Repeat("0", 64)
			want = 409
		case "analysis":
			bad.AnalysisSHA256 = strings.Repeat("0", 64)
			want = 409
		case "target":
			bad.InstanceID = "hi-" + strings.Repeat("0", 32)
			want = 409
		case "actor":
			bad.ActorID = ""
		case "request":
			bad.RequestID = "bad"
		case "schema":
			bad.SchemaVersion = "bad"
		}
		if code, out := call(t, s, "POST", route, token, bad); code != want {
			t.Fatal(kind, code, out)
		}
	}
	r := loopbackRequest("POST", route, body)
	r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	ctx, cancel := context.WithCancel(r.Context())
	cancel()
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r.WithContext(ctx))
	if w.Code != 408 {
		t.Fatal("canceled preparation", w.Code)
	}
	grants, err := s.d.Store.ListGrants()
	if err != nil || len(grants) != 0 {
		t.Fatal("invalid input wrote authority", err)
	}
}

func TestImportedPermissionApprovalRechecksPayloadAndAudit(t *testing.T) {
	s, id, body := importPermissionFixture(t)
	route := "/v1/skill-imports/" + id + "/permissions"
	code, out := call(t, s, "POST", route, token, body)
	if code != 201 {
		t.Fatal(code, out)
	}
	g := out["grant"].(map[string]any)
	action := "/v1/grants/" + g["grant_id"].(string)
	if code, out := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": g["admission_id"], "platform": "hermes", "subject_id": "other"}); code != 400 || out["error"] != "grant_import_preparation_required" {
		t.Fatal("generic endpoint bypass", code, out)
	}
	if code, _ := call(t, s, "POST", route, token, body); code != 200 {
		t.Fatal(code)
	}
	events, err := s.d.Store.TailAudit(100)
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, event := range events {
		if event.Event == "skill_import_permission_prepare" {
			count++
		}
	}
	if count != 1 {
		t.Fatal("retry duplicated audit", count)
	}
	code, result := call(t, s, "POST", action+"/challenge", token, map[string]any{"expected_revision": 0, "actor_id": body.ActorID})
	if code != 200 {
		t.Fatal(code, result)
	}
	ch := result["challenge"].(map[string]any)
	if err := os.WriteFile(filepath.Join(s.d.Store.Dir, "skill-imports", "blobs", id, "payload", "SKILL.md"), []byte("changed after challenge"), 0600); err != nil {
		t.Fatal(err)
	}
	code, out = call(t, s, "POST", action+"/approve", token, map[string]any{"expected_revision": 0, "actor_id": body.ActorID, "challenge_id": ch["challenge_id"], "nonce": ch["nonce"]})
	if code != 409 || out["error"] != "skill_import_changed" {
		t.Fatal("approved changed candidate", code, out)
	}
	current, revision, err := s.d.Store.GetGrantWithSeq(g["grant_id"].(string))
	if err != nil || current.Status != "pending_approval" || revision != 0 {
		t.Fatal("failed approval mutated grant", err)
	}
}
