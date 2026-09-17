package server

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/skillcontext"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

const (
	contextTestInstance = "hi-0123456789abcdef0123456789abcdef"
	contextTestAgent    = "hri-0123456789abcdef0123456789abcdef"
	contextTestSession  = "native-session"
	contextTestTask     = "native-task"
	contextTestInstall  = "ins-native-test"
	contextTestGrant    = "grt-native-test"
)

func attachSkillContextStore(t *testing.T, s *Server) *skillcontext.Store {
	t.Helper()
	now := time.Now().UTC()
	version := "1.0.0"
	g := &grant.Grant{
		GrantID: contextTestGrant, AdmissionID: "adm-context-test", Platform: "hermes", Status: "deployed",
		CreatedAt: now.Add(-time.Hour).Format(time.RFC3339),
		Subject:   grant.Subject{Type: "agent_instance", ID: contextTestAgent},
		Skill:     &grant.SkillRef{SkillID: "marketplace:skill:native-test@0123456789ab", Version: &version, ContentHash: strings.Repeat("1", 64)},
	}
	install := &skillinstall.Record{
		SchemaVersion: "local-skill-install-record/v1", InstallID: contextTestInstall,
		Plan:           skillinstall.Plan{PlanID: "plan-context-test", GrantID: contextTestGrant, Platform: "hermes", InstanceID: contextTestInstance},
		ClaimSignature: strings.Repeat("a", 128), RecordedStatus: "installed_unverified",
	}
	instance := runtimeidentity.Record{SchemaVersion: "local-runtime-identity/v1", InstanceID: contextTestInstance, AgentID: contextTestAgent, Platform: "hermes"}
	instance.GrantRef.GrantID = contextTestGrant
	store, err := skillcontext.Open(s.d.Store.Dir, skillcontext.Deps{
		Key: s.d.Key, Now: func() time.Time { return now },
		ReadGrant: func(id string) (*grant.Grant, error) {
			if id != contextTestGrant {
				return nil, os.ErrNotExist
			}
			return g, nil
		},
		ReadInstall: func(id string) (*skillinstall.Record, error) {
			if id != contextTestInstall {
				return nil, os.ErrNotExist
			}
			return install, nil
		},
		ReadInstance: func(id string) (runtimeidentity.Record, error) {
			if id != contextTestInstance {
				return runtimeidentity.Record{}, os.ErrNotExist
			}
			return instance, nil
		},
		SessionBound: func(platform, agentID, sessionID, grantID string) (time.Time, error) {
			if platform != "hermes" || agentID != contextTestAgent || sessionID != contextTestSession || grantID != contextTestGrant {
				return time.Time{}, os.ErrNotExist
			}
			return now.Add(2 * time.Hour), nil
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	s.skillContexts = store
	return store
}

func skillContextIssueBody() map[string]any {
	return map[string]any{
		"schema_version": skillcontext.IssueRequestSchema, "instance_id": contextTestInstance,
		"session_id": contextTestSession, "task_id": contextTestTask, "install_id": contextTestInstall,
		"ttl_seconds": 3600, "actor_id": "fixture-operator", "confirm_issue": true,
	}
}

func rawContextCall(s *Server, method, path, credential string, body any) *httptest.ResponseRecorder {
	req := loopbackRequest(method, path, body)
	if credential != "" {
		req.Header.Set("Authorization", "Bearer "+credential)
	}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	return w
}

func TestSkillContextHTTPAdminIssueReadAndExactRevoke(t *testing.T) {
	s, stateStore := newServer(t, "block")
	contexts := attachSkillContextStore(t, s)

	for _, credential := range []string{"", token} {
		w := rawContextCall(s, http.MethodPost, "/v1/skill-contexts", credential, skillContextIssueBody())
		if w.Code != http.StatusUnauthorized && w.Code != http.StatusForbidden {
			t.Fatalf("non-admin issued SEC: %d %s", w.Code, w.Body.String())
		}
	}
	code, issued := call(t, s, http.MethodPost, "/v1/skill-contexts", token, skillContextIssueBody())
	if code != http.StatusCreated || issued["schema_version"] != skillcontext.Schema || issued["signature"] == "" {
		t.Fatalf("issue: %d %v", code, issued)
	}
	id := issued["context_id"].(string)
	signature := issued["signature"].(string)
	if code, got := call(t, s, http.MethodGet, "/v1/skill-contexts/"+id, token, nil); code != http.StatusOK || got["signature"] != signature {
		t.Fatalf("get: %d %v", code, got)
	}

	badRevoke := map[string]any{"schema_version": skillcontext.RevokeRequestSchema, "expected_context_signature": strings.Repeat("0", 128), "actor_id": "fixture-operator", "confirm_revoke": true}
	if code, out := call(t, s, http.MethodPost, "/v1/skill-contexts/"+id+"/revoke", token, badRevoke); code != http.StatusConflict || out["error"] != "skill_context_changed" {
		t.Fatalf("stale revoke: %d %v", code, out)
	}
	if v, err := contexts.Verify("hermes", contextTestAgent, contextTestSession, contextTestTask); err != nil || v == nil || v.Invalid {
		t.Fatalf("stale revoke changed context: %+v %v", v, err)
	}
	revoke := map[string]any{"schema_version": skillcontext.RevokeRequestSchema, "expected_context_signature": signature, "actor_id": "fixture-revoker", "confirm_revoke": true}
	if code, out := call(t, s, http.MethodPost, "/v1/skill-contexts/"+id+"/revoke", token, revoke); code != http.StatusOK || out["schema_version"] != skillcontext.RevocationSchema {
		t.Fatalf("revoke: %d %v", code, out)
	}
	if v, err := contexts.Verify("hermes", contextTestAgent, contextTestSession, contextTestTask); err != nil || v == nil || !v.Invalid || v.ReasonCode != "skill_context_revoked" {
		t.Fatalf("revocation not live: %+v %v", v, err)
	}

	events, err := stateStore.TailAudit(20)
	if err != nil {
		t.Fatal(err)
	}
	var issueAudit, revokeAudit bool
	for _, event := range events {
		issueAudit = issueAudit || event.Event == "skill_context_issue_authorized" && event.ActorID == "fixture-operator" && event.Target == contextTestInstall
		revokeAudit = revokeAudit || event.Event == "skill_context_revoke_authorized" && event.ActorID == "fixture-revoker" && event.Target == id
		if strings.Contains(event.Note, contextTestSession) || strings.Contains(event.Note, contextTestTask) {
			t.Fatal("audit leaked native identifiers")
		}
	}
	if !issueAudit || !revokeAudit {
		t.Fatalf("missing management audit: issue=%v revoke=%v events=%v", issueAudit, revokeAudit, events)
	}
}

func TestSkillContextHTTPStrictRequestsAndMethods(t *testing.T) {
	s, _ := newServer(t, "block")
	attachSkillContextStore(t, s)
	valid := skillContextIssueBody()
	for name, mutate := range map[string]func(map[string]any){
		"unknown":       func(v map[string]any) { v["grant_id"] = contextTestGrant },
		"confirm":       func(v map[string]any) { v["confirm_issue"] = false },
		"ttl_low":       func(v map[string]any) { v["ttl_seconds"] = 59 },
		"ttl_float":     func(v map[string]any) { v["ttl_seconds"] = 60.5 },
		"actor_control": func(v map[string]any) { v["actor_id"] = "bad\nactor" },
		"bad_instance":  func(v map[string]any) { v["instance_id"] = "../escape" },
	} {
		t.Run(name, func(t *testing.T) {
			body := map[string]any{}
			for key, value := range valid {
				body[key] = value
			}
			mutate(body)
			if code, out := call(t, s, http.MethodPost, "/v1/skill-contexts", token, body); code != http.StatusBadRequest || out["error"] != skillContextRequestError {
				t.Fatalf("%d %v", code, out)
			}
		})
	}
	if code, _ := call(t, s, http.MethodPost, "/v1/skill-contexts", token, `{"schema_version":"local-skill-execution-context-issue/v1","schema_version":"local-skill-execution-context-issue/v1"}`); code != http.StatusBadRequest {
		t.Fatal("duplicate or partial object accepted", code)
	}
	if code, _ := call(t, s, http.MethodGet, "/v1/skill-contexts", token, nil); code != http.StatusMethodNotAllowed {
		t.Fatal("collection method", code)
	}
	if code, _ := call(t, s, http.MethodPost, "/v1/skill-contexts/missing", token, nil); code != http.StatusMethodNotAllowed {
		t.Fatal("item method", code)
	}
	entries, err := os.ReadDir(filepath.Join(s.d.Store.Dir, "skill-contexts"))
	if err != nil || len(entries) != 0 {
		t.Fatalf("rejected requests wrote contexts: %v %d", err, len(entries))
	}
}

func TestSkillContextHTTPAuditFailureClosesWrite(t *testing.T) {
	s, _ := newServer(t, "block")
	attachSkillContextStore(t, s)
	if err := os.Mkdir(filepath.Join(s.d.Store.Dir, "audit.jsonl"), 0o700); err != nil {
		t.Fatal(err)
	}
	if code, out := call(t, s, http.MethodPost, "/v1/skill-contexts", token, skillContextIssueBody()); code != http.StatusInternalServerError || out["error"] != "skill_context_audit_failed" {
		t.Fatalf("audit failure: %d %v", code, out)
	}
	entries, err := os.ReadDir(filepath.Join(s.d.Store.Dir, "skill-contexts"))
	if err != nil || len(entries) != 0 {
		t.Fatalf("audit failure published authority: %v %d", err, len(entries))
	}
}
