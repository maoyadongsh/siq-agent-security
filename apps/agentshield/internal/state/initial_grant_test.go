package state

import (
	"errors"
	"sync"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestInitialGrantIdenticalConcurrentCommitHasOneCreator(t *testing.T) {
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	// Exact same bytes, including the clock value, reproduce the replay path
	// deterministically instead of relying on OS clock resolution and timing.
	c := GrantCommit{Grant: grant.Grant{GrantID: "draft", Status: "pending_approval"}, ExpectedRevision: -1,
		Audit: &AuditEvent{At: "2026-09-28T00:00:00Z", Event: "grant_instance_draft", Target: "draft"}}
	results := make(chan error, 3)
	var wg sync.WaitGroup
	for range 3 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			seq, err := s.CommitInitialGrant(c)
			if seq != 0 {
				t.Errorf("unexpected revision %d", seq)
			}
			results <- err
		}()
	}
	wg.Wait()
	close(results)
	created := 0
	for err := range results {
		if err == nil {
			created++
		} else if !errors.Is(err, ErrRevisionConflict) {
			t.Fatal(err)
		}
	}
	if created != 1 {
		t.Fatalf("identical replay reported %d creators", created)
	}
	// Existing explicit replay consumers retain their original behavior.
	if seq, err := s.CommitGrant(c); err != nil || seq != 0 {
		t.Fatal("ordinary transaction replay changed", seq, err)
	}
	audit, err := s.TailAudit(10)
	if err != nil || len(audit) != 1 || audit[0].Event != "grant_instance_draft" {
		t.Fatal("replay duplicated audit", audit, err)
	}
	g, seq, err := s.GetGrantWithSeq("draft")
	if err != nil || seq != 0 || g.Status != "pending_approval" || g.ApprovedBy != nil || g.EffectiveReadback != nil {
		t.Fatal("replay changed grant authority", g, seq, err)
	}
	c.ExpectedRevision = 0
	if _, err := s.CommitInitialGrant(c); err == nil {
		t.Fatal("initial creator accepted an update")
	}
}
