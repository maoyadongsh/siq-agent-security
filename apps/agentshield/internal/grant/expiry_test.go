package grant

import (
	"errors"
	"testing"
	"time"
)

func TestExpirationBoundaryAndInvalidDeadline(t *testing.T) {
	for _, tc := range []struct {
		name, value string
		delta       time.Duration
		want        error
	}{
		{"before", fixedNow.Format(time.RFC3339Nano), -time.Nanosecond, nil},
		{"equal", fixedNow.Format(time.RFC3339Nano), 0, ErrExpired},
		{"after", fixedNow.Format(time.RFC3339Nano), time.Nanosecond, ErrExpired},
		{"empty", "", 0, ErrInvalidExpiry},
		{"malformed", "tomorrow", 0, ErrInvalidExpiry},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if err := ValidateLifetime(Grant{ExpiresAt: &tc.value}, fixedNow.Add(tc.delta)); !errors.Is(err, tc.want) {
				t.Fatal(err)
			}
		})
	}
	if err := ValidateLifetime(Grant{}, fixedNow); err != nil {
		t.Fatal(err)
	}
}

func TestExpirationBindsChallengeAndCannotExtendApprovedGrant(t *testing.T) {
	g := build(t, "hermes", sampleAdmission()).Grant
	ch, err := IssueChallenge(g, 1, fixedNow)
	if err != nil {
		t.Fatal(err)
	}
	deadline := fixedNow.Add(time.Minute)
	out, err := SetExpiration(g, &deadline, fixedNow, key(t))
	if err != nil || g.ExpiresAt != nil || out.Signature == g.Signature {
		t.Fatal("deadline must be a signed copy", err)
	}
	if err := ValidateChallenge(*ch, out, 1, ch.Nonce, fixedNow); err != ErrChallengeMismatch {
		t.Fatal(err)
	}
	ch, err = IssueChallenge(out, 2, fixedNow)
	if err != nil {
		t.Fatal(err)
	}
	if ch.ExpiresAt != deadline.Format(time.RFC3339Nano) {
		t.Fatal("challenge outlives grant")
	}
	if err := ValidateChallenge(*ch, out, 2, ch.Nonce, deadline); err != ErrExpired {
		t.Fatal(err)
	}
	if _, err := IssueChallenge(out, 2, deadline); err != ErrExpired {
		t.Fatal(err)
	}
	if _, err := SetExpiration(g, &fixedNow, fixedNow, key(t)); err != ErrExpired {
		t.Fatal(err)
	}
	cleared, err := SetExpiration(out, nil, fixedNow, key(t))
	if err != nil || cleared.ExpiresAt != nil {
		t.Fatal(err)
	}
	for _, status := range []string{"approved", "deployed", "effective", "revoked", "rejected"} {
		out.Status = status
		if _, err := SetExpiration(out, nil, fixedNow, key(t)); err == nil {
			t.Fatalf("extended %s", status)
		}
	}
}

func TestExpiredGrantCannotAdvanceLifecycle(t *testing.T) {
	g := build(t, "hermes", sampleAdmission()).Grant
	past := time.Now().Add(-time.Hour).UTC().Format(time.RFC3339Nano)
	g.ExpiresAt = &past
	if _, err := Approve(g, human(), key(t)); err != ErrExpired {
		t.Fatal(err)
	}
	g.Status = "approved"
	if _, err := MarkDeployed(g, key(t)); err != ErrExpired {
		t.Fatal(err)
	}
	g.Status = "deployed"
	if _, err := MarkEffective(g, Readback{}, nil, key(t)); err != ErrExpired {
		t.Fatal(err)
	}
	if _, err := Revoke(g, key(t)); err != nil {
		t.Fatal("expired grant must remain revocable", err)
	}
	deadline := fixedNow.Add(time.Minute)
	r, err := Build(sampleAdmission(), Options{Platform: "hermes", Subject: Subject{Type: "agent_instance", ID: "expiry-test"}, Now: fixedNow, ExpiresAt: &deadline, Key: key(t)})
	if err != nil || r.Grant.ExpiresAt == nil {
		t.Fatal(err)
	}
	_, err = Build(sampleAdmission(), Options{Platform: "hermes", Now: deadline, ExpiresAt: &deadline, Key: key(t)})
	if err != ErrExpired {
		t.Fatal(err)
	}
}
