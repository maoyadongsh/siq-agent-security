package server

import (
	"net/http"
	"siq-agent-security/apps/agentshield/internal/skillcontext"
	"testing"
	"time"
)

func TestSkillContextManagementAdminAndStrictQuery(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, credential := range []string{"", token} {
		w := rawContextCall(s, http.MethodGet, "/v1/skill-contexts/management?install_id=missing", credential, nil)
		if w.Code != http.StatusUnauthorized && w.Code != http.StatusForbidden {
			t.Fatalf("non-admin: %d", w.Code)
		}
	}
	for _, query := range []string{"", "?install_id=", "?install_id=a&install_id=b", "?install_id=a&session_id=b", "?install_id=a&bad=%xx"} {
		w := rawContextCall(s, http.MethodGet, "/v1/skill-contexts/management"+query, s.bootAdmin, nil)
		if w.Code != http.StatusBadRequest {
			t.Fatalf("query %q: %d", query, w.Code)
		}
	}
	w := rawContextCall(s, http.MethodPost, "/v1/skill-contexts/management", s.bootAdmin, nil)
	if w.Code != http.StatusMethodNotAllowed {
		t.Fatal(w.Code)
	}
}

func TestServerReplacesLegacySECInstallReaderOnce(t *testing.T) {
	s, _ := newServer(t, "block")
	contexts := attachSkillContextStore(t, s)
	deps := s.d
	deps.SkillContexts = contexts
	next, err := New(deps)
	if err != nil {
		t.Fatal(err)
	}
	if next.skillContexts != contexts {
		t.Fatal("replaced SEC authority instead of its installation reader")
	}
	// The injected legacy fixture claims an installation that does not exist in
	// the server's signed installation store. Startup must stop trusting it.
	_, err = contexts.Issue(skillcontext.IssueRequest{InstanceID: contextTestInstance, SessionID: contextTestSession, InstallID: contextTestInstall, TTL: time.Hour})
	if err == nil {
		t.Fatal("legacy-only installation was accepted after server initialization")
	}
	if err := contexts.BindInstallationStore(next.skillInstallations); err == nil {
		t.Fatal("installation reader could be rebound after initialization")
	}
}
