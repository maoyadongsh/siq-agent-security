package runtimeidentity

import (
	"siq-agent-security/apps/agentshield/internal/intent"
	"testing"
)

func TestOpenClawEpochEnrollmentCreatesIndependentIntent(t *testing.T) {
	s, request := openClawFixture(t)
	r, token := create(t, s, request)
	a, _ := intent.OpenClawSessionID("agent:fixture:main", "11111111-1111-4111-8111-111111111111")
	b, _ := intent.OpenClawSessionID("agent:fixture:main", "22222222-2222-4222-8222-222222222222")
	first, err := s.Enroll(token, a)
	if err != nil {
		t.Fatal(err)
	}
	retry, err := s.Enroll(token, a)
	if err != nil || retry.Signature != first.Signature {
		t.Fatal("same epoch not idempotent", err)
	}
	if _, err = s.AuthorizeSession(token, r.Platform, r.AgentID, b); err == nil {
		t.Fatal("new epoch authorized before enrollment")
	}
	second, err := s.Enroll(token, b)
	if err != nil || second.IntentID == first.IntentID || second.BindingID == first.BindingID {
		t.Fatal("new epoch reused authority", err)
	}
	if _, err = s.AuthorizeSession(token, r.Platform, r.AgentID, b); err != nil {
		t.Fatal("new valid epoch cannot run", err)
	}
	if _, err = s.Enroll(token, "agent:fixture:main"); err == nil {
		t.Fatal("routing key enrolled")
	}
	if _, err = s.intents.RevokeBinding(second.BindingID, second.IntentDigest); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Enroll(token, b); err == nil {
		t.Fatal("revoked epoch resurrected")
	}
}
