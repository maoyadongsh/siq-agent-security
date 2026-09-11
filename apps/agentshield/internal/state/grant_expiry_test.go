package state

import (
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestExpiredNewestGrantDoesNotFallBackToOlderAuthority(t *testing.T) {
	store, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	expired := "2026-09-04T07:00:00Z"
	for _, g := range []grant.Grant{
		{GrantID: "old-unlimited", Platform: "hermes", Subject: grant.Subject{ID: "expiry-agent"}, Status: "deployed", CreatedAt: "2026-09-03T06:00:00Z"},
		{GrantID: "new-expired", Platform: "hermes", Subject: grant.Subject{ID: "expiry-agent"}, Status: "deployed", CreatedAt: "2026-09-04T06:00:00Z", ExpiresAt: &expired},
	} {
		if _, err := store.PutGrantCAS(g, -1); err != nil {
			t.Fatal(err)
		}
	}
	g := store.ActiveGrant("hermes", "expiry-agent")
	if g == nil || g.GrantID != "new-expired" || g.ExpiresAt == nil {
		t.Fatal("lookup resurrected older grant")
	}
}
