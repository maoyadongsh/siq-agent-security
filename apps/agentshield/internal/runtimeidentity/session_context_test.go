package runtimeidentity

import (
	"os"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
)

func TestEnrollmentContextNeverReusesAuthorityAcrossCalls(t *testing.T) {
	s, req, g := fixture(t)
	issued, token := create(t, s, req)
	r, b, err := s.EnrollContext(token, "context-session")
	if err != nil || r.IdentityID != issued.IdentityID || r.AgentID != b.AgentID {
		t.Fatal("response context differs from enrolled identity", err)
	}
	if _, _, err := s.AuthorizeSessionContext(token, r.Platform, r.AgentID, b.SessionID); err != nil {
		t.Fatal(err)
	}
	revoked, err := grant.Revoke(*g, s.key)
	if err != nil {
		t.Fatal(err)
	}
	*g = revoked
	if _, _, err := s.EnrollContext(token, b.SessionID); err == nil {
		t.Fatal("revoked Grant reused by context enrollment")
	}
	if _, _, err := s.AuthorizeSessionContext(token, r.Platform, r.AgentID, b.SessionID); err == nil {
		t.Fatal("selected Grant revocation skipped")
	}
}

func TestEnrollmentContextRechecksGrantBeforeBindingPublication(t *testing.T) {
	s, req, g := fixture(t)
	r, token := create(t, s, req)
	calls := 0
	store, err := intent.Open(s.dir, s.key, func(id string) (*grant.Grant, int, error) {
		if id != g.GrantID {
			return nil, 0, os.ErrNotExist
		}
		calls++
		if calls == 2 {
			revoked, err := grant.Revoke(*g, s.key)
			if err != nil {
				return nil, 0, err
			}
			*g = revoked
		}
		return g, 3, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	s.intents = store
	if _, _, err := s.EnrollContext(token, "revoked-during-enroll"); err == nil {
		t.Fatal("changed Grant reached binding publication")
	}
	if calls < 2 {
		t.Fatal("publication never rechecked current Grant")
	}
	_, binding, _ := store.ResolveBinding(r.Platform, "revoked-during-enroll", r.AgentID)
	if binding != nil {
		t.Fatal("failed revalidation published a binding")
	}
}
