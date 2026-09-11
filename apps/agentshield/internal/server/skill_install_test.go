package server

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

func installPlanHTTPFixture(t *testing.T, withTools ...bool) (*Server, skillinstall.Request, string) {
	t.Helper()
	s, id, permission := importPermissionFixture(t)
	code, out := call(t, s, "POST", "/v1/skill-imports/"+id+"/permissions", token, permission)
	if code != 201 {
		t.Fatal(code, out)
	}
	g := out["grant"].(map[string]any)
	route := "/v1/grants/" + g["grant_id"].(string)
	revision := 0
	if len(withTools) > 0 && withTools[0] {
		code, out = call(t, s, "POST", route+"/patch-desired", token, map[string]any{"expected_revision": revision, "actor_id": permission.ActorID, "tools": []string{"read_file"}})
		if code != 200 {
			t.Fatal(code, out)
		}
		revision = int(out["state_revision"].(float64))
	}

	code, out = call(t, s, "POST", route+"/challenge", token, map[string]any{"expected_revision": revision, "actor_id": permission.ActorID})
	if code != 200 {
		t.Fatal(code, out)
	}
	ch := out["challenge"].(map[string]any)
	code, out = call(t, s, "POST", route+"/approve", token, map[string]any{"expected_revision": revision, "actor_id": permission.ActorID, "challenge_id": ch["challenge_id"], "nonce": ch["nonce"]})
	if code != 200 {
		t.Fatal(code, out)
	}
	return s, skillinstall.Request{SchemaVersion: "local-skill-install-stage-create/v1", RequestID: "is-" + strings.Repeat("c", 32), GrantID: g["grant_id"].(string), ExpectedRevision: revision + 1, InstanceID: permission.InstanceID, DirectoryName: "example", ActorID: permission.ActorID}, id
}
func TestSkillInstallHTTPPrepareReadRetryAndRevoke(t *testing.T) {
	s, body, _ := installPlanHTTPFixture(t)
	route := "/v1/skill-installations/plans"
	code, out := call(t, s, "POST", route, token, body)
	if code != 201 || out["reused"] != false {
		t.Fatal(code, out)
	}
	p := out["plan"].(map[string]any)
	id := p["plan_id"].(string)
	if p["installed"] != false || p["runtime_verified"] != false || p["grant_revision"] != float64(1) {
		t.Fatal("wrong plan", p)
	}
	root, err := hermeshome.Resolve(s.hermesRoots(), body.InstanceID)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(root.Path, "skills", "example")); !os.IsNotExist(err) {
		t.Fatal("platform changed", err)
	}
	if code, again := call(t, s, "POST", route, token, body); code != 200 || again["reused"] != true || again["plan"].(map[string]any)["signature"] != p["signature"] {
		t.Fatal("retry replaced plan", code, again)
	}
	if code, again := call(t, s, "GET", route+"/"+id, token, nil); code != 200 || again["signature"] != p["signature"] {
		t.Fatal("load failed", code, again)
	}
	g, rev, err := s.d.Store.GetGrantWithSeq(body.GrantID)
	if err != nil || rev != 1 || g.Status != "approved" {
		t.Fatal("preview mutated authority", err)
	}
	code, out = call(t, s, "POST", "/v1/grants/"+body.GrantID+"/revoke", token, map[string]any{"expected_revision": 1, "actor_id": body.ActorID})
	if code != 200 {
		t.Fatal(code, out)
	}
	if code, out := call(t, s, "GET", route+"/"+id, token, nil); code != 409 || out["error"] != "skill_install_changed" {
		t.Fatal("revoked preview accepted", code, out)
	}
}
func TestSkillInstallHTTPAdminStrictnessAndFailures(t *testing.T) {
	s, body, importID := installPlanHTTPFixture(t)
	route := "/v1/skill-installations/plans"
	for _, method := range []string{"POST", "GET"} {
		for _, credential := range []string{"", token} {
			path := route
			if method == "GET" {
				path += "/sip-" + strings.Repeat("0", 64)
			}
			r := loopbackRequest(method, path, body)
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
				t.Fatal("admin capability", w.Code)
			}
		}
	}
	raw, _ := json.Marshal(body)
	for _, bad := range []string{`{}`, strings.Replace(string(raw), `"expected_revision":1`, `"expected_revision":null`, 1), strings.Replace(string(raw), `"actor_id":`, `"actor_id":"duplicate","actor_id":`, 1), strings.TrimSuffix(string(raw), "}") + `,"target_path":"/escape"}`} {
		r := loopbackRequest("POST", route, bad)
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		r.RemoteAddr = "127.0.0.1:12345"
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 400 {
			t.Fatal("strict body", w.Code, w.Body.String())
		}
	}
	wrong := body
	wrong.ExpectedRevision = 0
	if code, out := call(t, s, "POST", route, token, wrong); code != 409 {
		t.Fatal(code, out)
	}
	s.skillImportMu.Lock()
	code, out := call(t, s, "POST", route, token, body)
	s.skillImportMu.Unlock()
	if code != 429 || out["error"] != "skill_install_busy" {
		t.Fatal("shared slot", code, out)
	}
	r := loopbackRequest("POST", route, body)
	r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	ctx, cancel := context.WithCancel(r.Context())
	cancel()
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r.WithContext(ctx))
	if w.Code != 408 {
		t.Fatal("cancellation", w.Code)
	}
	if code, out := call(t, s, "POST", route, token, body); code != 201 {
		t.Fatal(code, out)
	}
	if err := os.WriteFile(filepath.Join(s.d.Store.Dir, "skill-imports", "blobs", importID, "payload", "SKILL.md"), []byte("changed"), 0600); err != nil {
		t.Fatal(err)
	}
	if code, out := call(t, s, "POST", route, token, body); code != 409 || out["error"] != "skill_install_changed" {
		t.Fatal("changed source reused", code, out)
	}
}
func TestSkillInstallCreatedContractSample(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/contracts/local-skill-install-plan.v1.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	var plan skillinstall.Plan
	if err := json.Unmarshal(raw, &plan); err != nil {
		t.Fatal(err)
	}
	output, err := json.MarshalIndent(installPlanCreated{"local-skill-install-plan-created/v1", &plan, false}, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	output = append(output, '\n')
	path := "../../testdata/contracts/local-skill-install-plan-created.v1.sample.json"
	if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
		if err := os.WriteFile(path, output, 0600); err != nil {
			t.Fatal(err)
		}
	}
	expected, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(expected, output) {
		t.Fatal("plan-created contract differs", err)
	}
}

func appliedHTTPFixture(t *testing.T, withTools ...bool) (*Server, skillinstall.ApplyRequest, string) {
	t.Helper()
	s, stage, _ := installPlanHTTPFixture(t, withTools...)
	code, out := call(t, s, "POST", "/v1/skill-installations/plans", token, stage)
	if code != 201 {
		t.Fatal(code, out)
	}
	p := out["plan"].(map[string]any)
	req := skillinstall.ApplyRequest{SchemaVersion: "local-skill-install-apply/v1", PlanID: p["plan_id"].(string), PlanSignature: p["signature"].(string), ActorID: stage.ActorID, ConfirmInstall: true}
	return s, req, stage.GrantID
}

func TestSkillInstallHTTPApplyReadRetry(t *testing.T) {
	s, req, grantID := appliedHTTPFixture(t)
	route := "/v1/skill-installations/apply"
	code, out := call(t, s, "POST", route, token, req)
	if code != 200 || out["status"] != "installed_unverified" {
		t.Fatal(code, out)
	}
	id := out["install_id"].(string)
	operation := "/v1/skill-installations/operations/" + id
	before, _ := json.Marshal(out)
	for _, method := range []string{"GET", "POST"} {
		path := operation
		var body any
		if method == "POST" {
			path = route
			body = req
		}
		code, again := call(t, s, method, path, token, body)
		after, _ := json.Marshal(again)
		if code != 200 || !bytes.Equal(before, after) {
			t.Fatal("retry/read changed evidence", code, again)
		}
	}
	g, rev, err := s.d.Store.GetGrantWithSeq(grantID)
	if err != nil || rev != 1 || g.Status != "approved" {
		t.Fatal("installation activated authority", err)
	}
	recover := installRecoverRequest{"local-skill-install-recover/v1", req.ActorID, true}
	if code, out := call(t, s, "POST", operation+"/recover", token, recover); code != 409 || out["error"] != "skill_install_conflict" {
		t.Fatal("success was uninstalled", code, out)
	}
	p := out["plan"].(map[string]any)
	root, err := hermeshome.Resolve(s.hermesRoots(), p["instance_id"].(string))
	if err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(root.Path, "skills", p["directory_name"].(string), "SKILL.md")
	if err := os.WriteFile(target, []byte("user changed"), 0600); err != nil {
		t.Fatal(err)
	}
	if code, out := call(t, s, "GET", operation, token, nil); code != 409 || out["error"] != "skill_install_changed" {
		t.Fatal("stale installed result", code, out)
	}
	if code, _ := call(t, s, "POST", operation+"/recover", token, recover); code != 409 {
		t.Fatal("changed success recovered", code)
	}
	content, err := os.ReadFile(target)
	if err != nil || string(content) != "user changed" {
		t.Fatal("user bytes lost", err)
	}
}

func TestSkillInstallHTTPOperationStrictness(t *testing.T) {
	s, req, _ := appliedHTTPFixture(t)
	id := strings.Replace(req.PlanID, "sip-", "sin-", 1)
	route := "/v1/skill-installations/operations/" + id
	recover := installRecoverRequest{"local-skill-install-recover/v1", req.ActorID, true}
	for _, test := range []struct {
		method, path string
		body         any
	}{
		{"POST", "/v1/skill-installations/apply", req}, {"GET", route, nil}, {"POST", route + "/recover", recover},
	} {
		for _, credential := range []string{"", token} {
			r := loopbackRequest(test.method, test.path, test.body)
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
				t.Fatal("admin boundary", w.Code)
			}
		}
	}
	for _, body := range []any{map[string]any{}, skillinstall.ApplyRequest{SchemaVersion: req.SchemaVersion, PlanID: req.PlanID, PlanSignature: req.PlanSignature, ActorID: req.ActorID}, map[string]any{"schema_version": req.SchemaVersion, "plan_id": req.PlanID, "plan_signature": req.PlanSignature, "actor_id": req.ActorID, "confirm_install": true, "target_path": "/escape"}} {
		if code, out := call(t, s, "POST", "/v1/skill-installations/apply", token, body); code != 400 {
			t.Fatal(code, out)
		}
	}
	for _, bad := range []string{`{}`, `{"schema_version":"local-skill-install-recover/v1","actor_id":"test","confirm_recovery":false}`, `{"schema_version":"local-skill-install-recover/v1","actor_id":"test","confirm_recovery":null}`, `{"schema_version":"local-skill-install-recover/v1","actor_id":"test","confirm_recovery":true,"actor_id":"other"}`} {
		r := loopbackRequest("POST", route+"/recover", bad)
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 400 {
			t.Fatal("strict recovery", w.Code)
		}
	}
	if code, _ := call(t, s, "GET", route, token, nil); code != 404 {
		t.Fatal("missing operation", code)
	}
	if code, _ := call(t, s, "GET", route+"/extra/path", token, nil); code != 404 {
		t.Fatal("extra route", code)
	}
	if code, _ := call(t, s, "GET", route+"/recover", token, nil); code != 405 {
		t.Fatal("recovery method", code)
	}
	s.skillImportMu.Lock()
	code, out := call(t, s, "POST", "/v1/skill-installations/apply", token, req)
	s.skillImportMu.Unlock()
	if code != 429 || out["error"] != "skill_install_busy" {
		t.Fatal("shared lock", code, out)
	}
	r := loopbackRequest("POST", "/v1/skill-installations/apply", req)
	r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	ctx, cancel := context.WithCancel(r.Context())
	cancel()
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r.WithContext(ctx))
	if w.Code != 408 {
		t.Fatal("canceled", w.Code)
	}
	if code, _ := call(t, s, "GET", route, token, nil); code != 404 {
		t.Fatal("cancellation wrote claim", code)
	}
}

func TestSkillInstallHTTPRecoveryWithoutSourceOrAuthority(t *testing.T) {
	s, req, grantID := appliedHTTPFixture(t)
	code, out := call(t, s, "POST", "/v1/skill-installations/apply", token, req)
	if code != 200 {
		t.Fatal(code, out)
	}
	id := out["install_id"].(string)
	// Simulate persisted state after publication but before final outcome. The
	// real process-exit windows are separately exercised in skillinstall tests.
	result := filepath.Join(s.d.Store.Dir, "skill-installations", "operations", id+".result.json")
	if err := os.Remove(result); err != nil {
		t.Fatal(err)
	}
	p := out["plan"].(map[string]any)
	source := p["source"].(map[string]any)
	if err := os.WriteFile(filepath.Join(s.d.Store.Dir, "skill-imports", "blobs", source["import_id"].(string), "payload", "SKILL.md"), []byte("broken source"), 0600); err != nil {
		t.Fatal(err)
	}
	if code, out := call(t, s, "POST", "/v1/grants/"+grantID+"/revoke", token, map[string]any{"expected_revision": 1, "actor_id": req.ActorID}); code != 200 {
		t.Fatal(code, out)
	}
	route := "/v1/skill-installations/operations/" + id
	if code, out := call(t, s, "GET", route, token, nil); code != 200 || out["status"] != "recovery_required" || out["operation"] != nil {
		t.Fatal("missing final projection", code, out)
	}
	root, err := hermeshome.Resolve(s.hermesRoots(), p["instance_id"].(string))
	if err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(root.Path, "skills", p["directory_name"].(string))
	foreign := filepath.Join(target, "user.txt")
	if err := os.WriteFile(foreign, []byte("user-owned"), 0600); err != nil {
		t.Fatal(err)
	}
	recover := installRecoverRequest{"local-skill-install-recover/v1", "recovery-user", true}
	if code, out := call(t, s, "POST", route+"/recover", token, recover); code != 409 || out["error"] != "skill_install_recovery_required" {
		t.Fatal("user file conflict", code, out)
	}
	if b, err := os.ReadFile(foreign); err != nil || string(b) != "user-owned" {
		t.Fatal("user file lost", err)
	}
	if err := os.Remove(foreign); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		if code, out := call(t, s, "POST", route+"/recover", token, recover); code != 200 || out["status"] != "rolled_back" {
			t.Fatal("recovery/retry", code, out)
		}
	}
	if _, err := os.Lstat(target); !os.IsNotExist(err) {
		t.Fatal("target remains", err)
	}
}

func TestSkillInstallViewContractSamples(t *testing.T) {
	var claim skillinstall.Claim
	var operation skillinstall.Operation
	for path, dst := range map[string]any{"claim": &claim, "operation": &operation} {
		raw, err := os.ReadFile("../../testdata/contracts/local-skill-install-" + path + ".v1.sample.json")
		if err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(raw, dst); err != nil {
			t.Fatal(err)
		}
	}
	view := skillinstall.View{SchemaVersion: "local-skill-install-view/v1", InstallID: claim.InstallID, Plan: claim.Plan, ClaimSignature: claim.Signature, Status: operation.Status, Operation: &operation}
	for kind, output := range map[string]any{"view": view, "recover": installRecoverRequest{"local-skill-install-recover/v1", "recovery-user", true}} {
		raw, err := json.MarshalIndent(output, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		raw = append(raw, '\n')
		path := "../../testdata/contracts/local-skill-install-" + kind + ".v1.sample.json"
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
		}
		want, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(want, raw) {
			t.Fatal("contract sample differs", kind, err)
		}
	}
}

func TestSkillInstallHTTPActivateAndRuntimeInvalidation(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		t.Run(mode, func(t *testing.T) {
			s, req, grantID := appliedHTTPFixture(t, true)
			if err := s.d.Engine.SetMode(mode); err != nil {
				t.Fatal(err)
			}
			code, out := call(t, s, "POST", "/v1/skill-installations/apply", token, req)
			if code != 200 {
				t.Fatal(code, out)
			}
			op := out["operation"].(map[string]any)
			plan := out["plan"].(map[string]any)
			route := "/v1/skill-installations/operations/" + out["install_id"].(string) + "/activate"
			activation := skillinstall.ActivateRequest{SchemaVersion: "local-skill-install-activate/v1", OperationSignature: op["signature"].(string), ExpectedRevision: int(plan["grant_revision"].(float64)), ActorID: "human-runtime", ConfirmInstanceScope: true}
			for _, credential := range []string{"", token} {
				r := loopbackRequest("POST", route, activation)
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
					t.Fatal("activation capability", w.Code)
				}
			}
			denied := activation
			denied.ConfirmInstanceScope = false
			if code, _ := call(t, s, "POST", route, token, denied); code != 400 {
				t.Fatal("implicit scope confirmation", code)
			}
			code, activated := call(t, s, "POST", route, token, activation)
			if code != 200 || activated["runtime_verified"] != false {
				t.Fatal(code, activated)
			}
			if code, again := call(t, s, "POST", route, token, activation); code != 200 || again["binding"].(map[string]any)["signature"] != activated["binding"].(map[string]any)["signature"] {
				t.Fatal("activation retry", code, again)
			}
			code, identity := call(t, s, "POST", "/v1/runtime-identities", token, map[string]any{"schema_version": "local-runtime-identity-create/v1", "instance_id": plan["instance_id"], "grant_id": grantID, "expected_grant_revision": activation.ExpectedRevision + 1, "actor_id": "human-runtime", "session_ttl_seconds": 600})
			if code != 201 {
				t.Fatal(code, identity)
			}
			raw, err := os.ReadFile(identity["credential_path"].(string))
			if err != nil {
				t.Fatal(err)
			}
			credential := string(raw)
			enroll := map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": "installed-native"}
			code, session := scopedCall(t, s, "/v1/runtime-sessions", credential, enroll)
			if code != 200 {
				t.Fatal(code, session)
			}
			if code, out := call(t, s, "POST", "/v1/grants/"+grantID+"/deploy", token, map[string]any{"expected_revision": activation.ExpectedRevision + 1, "actor_id": "human-runtime"}); code == 200 {
				t.Fatal("generic deployment escaped guard", out)
			}
			root, err := hermeshome.Resolve(s.hermesRoots(), plan["instance_id"].(string))
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(root.Path, "skills", "example", "SKILL.md"), []byte("user changed target"), 0600); err != nil {
				t.Fatal(err)
			}
			decision := map[string]any{"platform": "hermes", "agent_id": session["agent_id"], "session_id": "installed-native", "tool": "read_file", "params": map[string]any{"path": "/work/public/report"}}
			if code, out := scopedCall(t, s, "/v1/decide", credential, decision); code != 401 {
				t.Fatal("stale content passed runtime middleware", code, out)
			}
			if code, out := scopedCall(t, s, "/v1/runtime-sessions", credential, enroll); code != 401 {
				t.Fatal("stale content enrolled", code, out)
			}
			if code, out := call(t, s, "POST", route, token, activation); code != 409 {
				t.Fatal("stale activation reauthorized", code, out)
			}
		})
	}
}

func TestSkillInstallReadinessHTTP(t *testing.T) {
	for _, withTools := range []bool{false, true} {
		t.Run(fmt.Sprint(withTools), func(t *testing.T) {
			s, req, grantID := appliedHTTPFixture(t, withTools)
			code, v := call(t, s, "POST", "/v1/skill-installations/apply", token, req)
			if code != 200 {
				t.Fatal(code, v)
			}
			route := "/v1/skill-installations/operations/" + v["install_id"].(string)
			byGrant := "/v1/skill-installations/grants/" + grantID + "/runtime"
			for _, path := range []string{route + "/runtime", byGrant} {
				for _, credential := range []string{"", token} {
					r := loopbackRequest("GET", path, nil)
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
						t.Fatal("read capability", w.Code)
					}
				}
				if code, _ := call(t, s, "POST", path, token, nil); code != 405 {
					t.Fatal("read method", code)
				}
			}
			if code, _ := call(t, s, "GET", byGrant, token, nil); code != 404 {
				t.Fatal("unprepared lookup", code)
			}
			code, readiness := call(t, s, "GET", route+"/runtime", token, nil)
			want := "no_tools"
			if withTools {
				want = "not_prepared"
			}
			if code != 200 || readiness["status"] != want || readiness["binding"] != nil {
				t.Fatal(code, readiness)
			}
			plan := v["plan"].(map[string]any)
			activation := skillinstall.ActivateRequest{SchemaVersion: "local-skill-install-activate/v1", OperationSignature: v["operation"].(map[string]any)["signature"].(string), ExpectedRevision: int(plan["grant_revision"].(float64)), ActorID: "human", ConfirmInstanceScope: true}
			code, result := call(t, s, "POST", route+"/activate", token, activation)
			if !withTools {
				if code != 400 || result["error"] != "skill_install_no_tools" {
					t.Fatal(code, result)
				}
				if code, _ := call(t, s, "GET", byGrant, token, nil); code != 404 {
					t.Fatal("empty tools published binding", code)
				}
				return
			}
			if code != 200 {
				t.Fatal(code, result)
			}
			for _, path := range []string{route + "/runtime", byGrant} {
				code, r := call(t, s, "GET", path, token, nil)
				if code != 200 || r["status"] != "prepared" || r["state_revision"] != result["state_revision"] {
					t.Fatal(code, r)
				}
			}
		})
	}
}

func TestSkillInstallationCatalogAndInspectionHTTP(t *testing.T) {
	s, req, grantID := appliedHTTPFixture(t)
	code, v := call(t, s, "POST", "/v1/skill-installations/apply", token, req)
	if code != 200 {
		t.Fatal(code, v)
	}
	id := v["install_id"].(string)
	operationRoute := "/v1/skill-installations/operations/" + id
	for _, path := range []string{"/v1/skill-installations/operations", operationRoute + "/inspection"} {
		for _, credential := range []string{"", token} {
			r := loopbackRequest("GET", path, nil)
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
				t.Fatal("inspection capability", w.Code)
			}
		}
		if code, _ := call(t, s, "POST", path, token, nil); code != 405 {
			t.Fatal("read accepted write", code)
		}
	}
	code, list := call(t, s, "GET", "/v1/skill-installations/operations", token, nil)
	if code != 200 || list["platform_changes"] != false || len(list["items"].([]any)) != 1 {
		t.Fatal(code, list)
	}
	code, inspection := call(t, s, "GET", operationRoute+"/inspection", token, nil)
	if code != 200 || inspection["target_state"] != "matched" || inspection["comparison_complete"] != true {
		t.Fatal(code, inspection)
	}
	plan := v["plan"].(map[string]any)
	root, err := hermeshome.Resolve(s.hermesRoots(), plan["instance_id"].(string))
	if err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(root.Path, "skills", "example", "SKILL.md")
	if err := os.WriteFile(target, []byte("modified locally"), 0600); err != nil {
		t.Fatal(err)
	}
	code, inspection = call(t, s, "GET", operationRoute+"/inspection", token, nil)
	if code != 200 || inspection["target_state"] != "changed" || inspection["changes_total"] != float64(1) {
		t.Fatal(code, inspection)
	}
	if code, _ := call(t, s, "GET", operationRoute, token, nil); code != 409 {
		t.Fatal("strict installation read weakened", code)
	}
	code, list = call(t, s, "GET", "/v1/skill-installations/operations", token, nil)
	if code != 200 || list["items"].([]any)[0].(map[string]any)["recorded_status"] != "installed_unverified" {
		t.Fatal("history lost", code, list)
	}
	g, _, err := s.d.Store.GetGrantWithSeq(grantID)
	if err != nil || g.Status != "approved" {
		t.Fatal("read changed authority", err)
	}
	if raw, err := os.ReadFile(target); err != nil || string(raw) != "modified locally" {
		t.Fatal("read rewrote target", err)
	}
}
