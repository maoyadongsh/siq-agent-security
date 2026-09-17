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
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
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

func TestImportedPermissionAndInstallationSupportOpenClawInstance(t *testing.T) {
	s, req := skillImportHTTPFixture(t)
	root := filepath.Join(s.d.Home, ".openclaw")
	if err := os.MkdirAll(root, 0700); err != nil {
		t.Fatal(err)
	}
	if code, out := call(t, s, "POST", "/v1/skill-imports", token, req); code != 201 {
		t.Fatal(code, out)
	}
	record, _, err := s.skillImports.Load(nil, req.ImportID)
	if err != nil {
		t.Fatal(err)
	}
	body := importPermissionRequest{
		SchemaVersion: "local-skill-import-permission-create/v1",
		RequestID:     "ip-" + strings.Repeat("d", 32), ArtifactDigest: record.ArtifactDigest,
		AnalysisSHA256: record.AnalysisSHA256, InstanceID: hermeshome.Identifier(root), ActorID: "fixture-human",
	}
	code, result := call(t, s, "POST", "/v1/skill-imports/"+req.ImportID+"/permissions", token, body)
	if code != 201 {
		t.Fatal(code, result)
	}
	g := result["grant"].(map[string]any)
	if g["platform"] != "openclaw" || g["subject"].(map[string]any)["id"] != "hri-"+strings.TrimPrefix(body.InstanceID, "hi-") {
		t.Fatal("permission target was not bound to OpenClaw", g)
	}
	grantPath := "/v1/grants/" + g["grant_id"].(string)
	code, result = call(t, s, "POST", grantPath+"/patch-desired", token, map[string]any{
		"expected_revision": 0, "actor_id": body.ActorID, "tools": []string{"read"},
	})
	if code != 200 {
		t.Fatal(code, result)
	}
	challengeCode, challengeResult := call(t, s, "POST", grantPath+"/challenge", token, map[string]any{
		"expected_revision": result["state_revision"], "actor_id": body.ActorID,
	})
	if challengeCode != 200 {
		t.Fatal(challengeCode, challengeResult)
	}
	challenge := challengeResult["challenge"].(map[string]any)
	code, result = call(t, s, "POST", grantPath+"/approve", token, map[string]any{
		"expected_revision": result["state_revision"], "actor_id": body.ActorID,
		"challenge_id": challenge["challenge_id"], "nonce": challenge["nonce"],
	})
	if code != 200 {
		t.Fatal(code, result)
	}
	stage := skillinstall.Request{
		SchemaVersion: "local-skill-install-stage-create/v1", RequestID: "is-" + strings.Repeat("e", 32),
		GrantID: g["grant_id"].(string), ExpectedRevision: int(result["state_revision"].(float64)),
		InstanceID: body.InstanceID, DirectoryName: "openclaw-import", ActorID: body.ActorID,
	}
	code, planResult := call(t, s, "POST", "/v1/skill-installations/plans", token, stage)
	if code != 201 {
		t.Fatal(code, planResult)
	}
	plan := planResult["plan"].(map[string]any)
	if plan["platform"] != "openclaw" {
		t.Fatal("installation plan lost OpenClaw target", plan)
	}
	code, installed := call(t, s, "POST", "/v1/skill-installations/apply", token, skillinstall.ApplyRequest{
		SchemaVersion: "local-skill-install-apply/v1", PlanID: plan["plan_id"].(string),
		PlanSignature: plan["signature"].(string), ActorID: body.ActorID, ConfirmInstall: true,
	})
	if code != 200 || installed["status"] != "installed_unverified" {
		t.Fatal(code, installed)
	}
	operation := installed["operation"].(map[string]any)
	code, activated := call(t, s, "POST", "/v1/skill-installations/operations/"+installed["install_id"].(string)+"/activate", token, skillinstall.ActivateRequest{
		SchemaVersion: "local-skill-install-activate/v1", OperationSignature: operation["signature"].(string),
		ExpectedRevision: stage.ExpectedRevision, ActorID: body.ActorID, ConfirmInstanceScope: true,
	})
	if code != 200 || activated["runtime_verified"] != false {
		t.Fatal(code, activated)
	}
	targetSkill := filepath.Join(root, "skills", stage.DirectoryName, "SKILL.md")
	targetInfo, err := os.Stat(targetSkill)
	if err != nil {
		t.Fatal("OpenClaw Skill was not installed in the selected root", err)
	}
	pool := filepath.Join(root, ".siq-agent-security-installs", installed["install_id"].(string))
	entries, err := os.ReadDir(pool)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if !strings.HasPrefix(entry.Name(), "f-") {
			continue
		}
		poolInfo, statErr := os.Stat(filepath.Join(pool, entry.Name()))
		if statErr != nil {
			t.Fatal(statErr)
		}
		if os.SameFile(targetInfo, poolInfo) {
			t.Fatal("OpenClaw payload must be independently published; hardlinks are rejected by its Skill loader")
		}
	}
}

func TestImportedPermissionRejectsAmbiguousAndSymlinkOpenClawTargets(t *testing.T) {
	for _, test := range []struct {
		name      string
		configure func(*testing.T, *Server) string
	}{
		{
			name: "ambiguous",
			configure: func(t *testing.T, s *Server) string {
				root := filepath.Join(s.d.Home, ".openclaw")
				if err := os.MkdirAll(root, 0700); err != nil {
					t.Fatal(err)
				}
				s.d.HermesHome = root
				return hermeshome.Identifier(root)
			},
		},
		{
			name: "symlink",
			configure: func(t *testing.T, s *Server) string {
				real := filepath.Join(s.d.Home, "real-openclaw")
				root := filepath.Join(s.d.Home, ".openclaw")
				if err := os.MkdirAll(real, 0700); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(real, root); err != nil {
					t.Fatal(err)
				}
				return hermeshome.Identifier(root)
			},
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			s, req := skillImportHTTPFixture(t)
			instanceID := test.configure(t, s)
			if code, out := call(t, s, "POST", "/v1/skill-imports", token, req); code != 201 {
				t.Fatal(code, out)
			}
			record, _, err := s.skillImports.Load(nil, req.ImportID)
			if err != nil {
				t.Fatal(err)
			}
			body := importPermissionRequest{SchemaVersion: "local-skill-import-permission-create/v1", RequestID: "ip-" + strings.Repeat("f", 32), ArtifactDigest: record.ArtifactDigest, AnalysisSHA256: record.AnalysisSHA256, InstanceID: instanceID, ActorID: "fixture-human"}
			if code, out := call(t, s, "POST", "/v1/skill-imports/"+req.ImportID+"/permissions", token, body); code != 409 || out["error"] != "skill_import_permission_target_unavailable" {
				t.Fatal("unsafe target accepted", code, out)
			}
			grants, err := s.d.Store.ListGrants()
			if err != nil || len(grants) != 0 {
				t.Fatal("unsafe target wrote authority", err, grants)
			}
		})
	}
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
