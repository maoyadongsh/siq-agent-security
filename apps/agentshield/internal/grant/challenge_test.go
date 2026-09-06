package grant

import (
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
)

func TestApprovalChallengeReplayAndDigest(t *testing.T) {
	now := time.Date(2026, 9, 6, 12, 0, 0, 0, time.UTC)
	g := Grant{
		GrantID: "grt-test", AdmissionID: "adm-1",
		Subject:  Subject{Type: "agent_instance", ID: "a1"},
		Platform: "hermes", Status: "pending_approval",
		DefaultEffect: "deny", EnforcementMode: "block",
		Facts: []Fact{{
			FactID: "f1", Domain: "tool", Action: "read_file",
			Resource: admission.Resource{Type: "path", Value: "/tmp"}, Effect: "allow",
			State: "declared", Authority: "admission", EvidenceIDs: []string{"e1"},
		}},
	}
	ch, err := IssueChallenge(g, 0, now)
	if err != nil {
		t.Fatal(err)
	}
	if err := ValidateChallenge(*ch, g, 0, ch.Nonce, now); err != nil {
		t.Fatal(err)
	}
	if err := ValidateChallenge(*ch, g, 0, "deadbeef", now); err != ErrChallengeBadNonce {
		t.Fatalf("bad nonce: %v", err)
	}
	if err := ValidateChallenge(*ch, g, 1, ch.Nonce, now); err != ErrChallengeMismatch {
		t.Fatalf("wrong revision: %v", err)
	}
	// Scope change invalidates digest.
	g2 := g
	g2.Facts = append([]Fact{}, g.Facts...)
	g2.Facts[0].Resource.Value = "/etc"
	if err := ValidateChallenge(*ch, g2, 0, ch.Nonce, now); err != ErrChallengeMismatch {
		t.Fatalf("scope change must mismatch: %v", err)
	}
	consumed := MarkConsumed(*ch, now)
	if err := ValidateChallenge(consumed, g, 0, ch.Nonce, now); err != ErrChallengeConsumed {
		t.Fatalf("consumed: %v", err)
	}
	if err := ValidateChallenge(*ch, g, 0, ch.Nonce, now.Add(ChallengeTTL+time.Second)); err != ErrChallengeExpired {
		t.Fatalf("expired: %v", err)
	}
}

func TestBindingDigestStable(t *testing.T) {
	g := Grant{
		GrantID: "grt-x", AdmissionID: "adm", Subject: Subject{Type: "agent_instance", ID: "i"},
		Platform: "openclaw", Status: "pending_approval", DefaultEffect: "deny", EnforcementMode: "block",
	}
	a, err := BindingDigest(g)
	if err != nil {
		t.Fatal(err)
	}
	b, err := BindingDigest(g)
	if err != nil || a != b {
		t.Fatalf("unstable digest %s vs %s err=%v", a, b, err)
	}
}
