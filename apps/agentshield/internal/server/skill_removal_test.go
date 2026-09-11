package server

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

func TestSkillRemovalHTTPAuthorityAndRecovery(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		t.Run(mode, func(t *testing.T) {
			s, apply, grantID := appliedHTTPFixture(t, true)
			if err := s.d.Engine.SetMode(mode); err != nil {
				t.Fatal(err)
			}
			code, installed := call(t, s, "POST", "/v1/skill-installations/apply", token, apply)
			if code != 200 {
				t.Fatal(code, installed)
			}
			plan := installed["plan"].(map[string]any)
			route := "/v1/skill-installations/operations/" + installed["install_id"].(string)
			activation := skillinstall.ActivateRequest{SchemaVersion: "local-skill-install-activate/v1", OperationSignature: installed["operation"].(map[string]any)["signature"].(string), ExpectedRevision: int(plan["grant_revision"].(float64)), ActorID: "human-runtime", ConfirmInstanceScope: true}
			code, activated := call(t, s, "POST", route+"/activate", token, activation)
			if code != 200 {
				t.Fatal(code, activated)
			}
			code, identity := call(t, s, "POST", "/v1/runtime-identities", token, map[string]any{"schema_version": "local-runtime-identity-create/v1", "instance_id": plan["instance_id"], "grant_id": grantID, "expected_grant_revision": activated["state_revision"], "actor_id": "human-runtime", "session_ttl_seconds": 600})
			if code != 201 {
				t.Fatal(code, identity)
			}
			secret, err := os.ReadFile(identity["credential_path"].(string))
			if err != nil {
				t.Fatal(err)
			}
			enroll := map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": "before-removal"}
			code, session := scopedCall(t, s, "/v1/runtime-sessions", string(secret), enroll)
			if code != 200 {
				t.Fatal(code, session)
			}
			code, preview := call(t, s, "GET", route+"/removal", token, nil)
			if code != 200 || preview["status"] != "not_requested" || preview["claim"] != nil || preview["will_revoke_grant"] != true {
				t.Fatal("read mutated removal", code, preview)
			}
			req := skillinstall.RemoveRequest{SchemaVersion: "local-skill-install-remove/v1", OperationSignature: activation.OperationSignature, ExpectedGrantRevision: int(preview["state_revision"].(float64)), ExpectedBindingSignature: preview["binding_signature"].(string), ActorID: "human-removal", ConfirmRemove: true}
			root, err := hermeshome.Resolve(s.hermesRoots(), plan["instance_id"].(string))
			if err != nil {
				t.Fatal(err)
			}
			target := filepath.Join(root.Path, "skills", "example")
			userFile := filepath.Join(target, "user.txt")
			if err := os.WriteFile(userFile, []byte("user owns this"), 0600); err != nil {
				t.Fatal(err)
			}
			code, pending := call(t, s, "POST", route+"/removal", token, req)
			if code != 200 || pending["status"] != "cleanup_pending" || pending["result"] != nil || pending["grant"].(map[string]any)["status"] != "revoked" {
				t.Fatal("pending cleanup misreported", code, pending)
			}
			if raw, err := os.ReadFile(userFile); err != nil || string(raw) != "user owns this" {
				t.Fatal("unknown content changed", err)
			}
			if _, err := os.Stat(filepath.Join(target, "SKILL.md")); err != nil {
				t.Fatal("preflight partially deleted target", err)
			}
			decision := map[string]any{"platform": "hermes", "agent_id": session["agent_id"], "session_id": "before-removal", "tool": "read_file", "params": map[string]any{"path": "/work/public/report"}}
			if code, out := scopedCall(t, s, "/v1/decide", string(secret), decision); code != 401 {
				t.Fatal("old session authorized after removal", code, out)
			}
			enroll["session_id"] = "after-removal"
			if code, out := scopedCall(t, s, "/v1/runtime-sessions", string(secret), enroll); code != 401 {
				t.Fatal("new session authorized after removal", code, out)
			}
			if code, out := call(t, s, "POST", route+"/activate", token, activation); code != 409 || out["error"] != "skill_install_removal_pending" {
				t.Fatal("pending removal reactivated", code, out)
			}
			// Only the fixture's user removes the extra file; SIQ preserves it.
			if err := os.Remove(userFile); err != nil {
				t.Fatal(err)
			}
			code, result := call(t, s, "POST", route+"/removal", token, req)
			if code != 200 || result["status"] != "removed" || result["grant"] != nil || result["state_revision"] != nil {
				t.Fatal("recovery failed", code, result)
			}
			if _, err := os.Lstat(target); !os.IsNotExist(err) {
				t.Fatal("target retained", err)
			}
			if err := os.Mkdir(target, 0700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(userFile, []byte("new unrelated installation"), 0600); err != nil {
				t.Fatal(err)
			}
			code, again := call(t, s, "POST", route+"/removal", token, req)
			if code != 200 || again["result"].(map[string]any)["signature"] != result["result"].(map[string]any)["signature"] {
				t.Fatal("completed retry changed result", code, again)
			}
			if raw, err := os.ReadFile(userFile); err != nil || string(raw) != "new unrelated installation" {
				t.Fatal("completed retry touched new user target", err)
			}
		})
	}
}

func TestSkillRemovalHTTPAdminAndStrictRequest(t *testing.T) {
	s, apply, _ := appliedHTTPFixture(t)
	code, installed := call(t, s, "POST", "/v1/skill-installations/apply", token, apply)
	if code != 200 {
		t.Fatal(code, installed)
	}
	route := "/v1/skill-installations/operations/" + installed["install_id"].(string) + "/removal"
	code, view := call(t, s, "GET", route, token, nil)
	if code != 200 {
		t.Fatal(code, view)
	}
	req := skillinstall.RemoveRequest{SchemaVersion: "local-skill-install-remove/v1", OperationSignature: installed["operation"].(map[string]any)["signature"].(string), ExpectedGrantRevision: int(view["state_revision"].(float64)), ActorID: "human-removal", ConfirmRemove: true}
	for _, method := range []string{"GET", "POST"} {
		for _, credential := range []string{"", token} {
			r := loopbackRequest(method, route, req)
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
				t.Fatal("removal capability", w.Code)
			}
		}
	}
	raw, _ := json.Marshal(req)
	body := string(raw)
	for _, bad := range []string{`{}`, strings.Replace(body, `"confirm_remove":true`, `"confirm_remove":false`, 1), strings.Replace(body, `"expected_binding_signature":""`, `"expected_binding_signature":null`, 1), strings.Replace(body, `"expected_binding_signature":"",`, ``, 1), strings.Replace(body, `"expected_binding_signature":""`, `"expected_binding_signature":"invalid"`, 1), strings.Replace(body, `"actor_id":`, `"actor_id":"duplicate","actor_id":`, 1), strings.TrimSuffix(body, "}") + `,"target_path":"/escape"}`} {
		r := loopbackRequest("POST", route, bad)
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 400 || w.Header().Get("Cache-Control") != "no-store" {
			t.Fatal("strict removal", w.Code, w.Body.String())
		}
	}
	wrong := req
	wrong.ExpectedGrantRevision++
	if code, out := call(t, s, "POST", route, token, wrong); code != 409 {
		t.Fatal("stale removal accepted", code, out)
	}
	r := loopbackRequest("GET", route, nil)
	r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	if w.Code != 200 || w.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("removal read cache", w.Code)
	}
	var unchanged skillinstall.RemovalView
	if err := json.Unmarshal(w.Body.Bytes(), &unchanged); err != nil || unchanged.Status != "not_requested" || unchanged.Claim != nil {
		t.Fatal("rejected requests changed removal", err)
	}
}
