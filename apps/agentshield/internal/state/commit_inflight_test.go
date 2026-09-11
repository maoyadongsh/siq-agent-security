package state

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
)

// Between a commit's grant publication and its done marker, readers must see
// ErrIncompleteCommit, and a duplicate committer of the same derived grant must
// wait on the commit lock and then converge on the committed document instead of
// publishing a replacement. This is the exact store-level sequence the draft
// HTTP route performs after the KIMI-001 fix (read → incomplete → CommitGrantFrom
// → conflict → re-read). Channels synchronize every step; the single bounded
// timeout only proves the duplicate is still blocked inside the window.
func TestInflightCommitBlocksDuplicateUntilSettled(t *testing.T) {
	st, _ := Open(t.TempDir())
	source := GrantCommit{Grant: grant.Grant{GrantID: "src", Status: "deployed", Platform: "hermes", Subject: grant.Subject{ID: "agent"}},
		ExpectedRevision: -1, DesiredPolicy: grant.DesiredPolicy{"policy_id": "pol-src", "version": 1},
		Audit: &AuditEvent{At: "2026-09-11T00:59:00Z", Event: "grant_deploy", Target: "src"}}
	if _, err := st.CommitGrant(source); err != nil {
		t.Fatal(err)
	}
	srcDoc, srcRev, err := st.GetGrantWithSeq("src")
	if err != nil || srcRev != 0 {
		t.Fatal(srcRev, err)
	}

	winner := GrantCommit{Grant: grant.Grant{GrantID: "draft", Status: "pending_approval", Platform: "hermes", Subject: grant.Subject{ID: "agent"}},
		ExpectedRevision: -1, DesiredPolicy: grant.DesiredPolicy{"policy_id": "pol-draft", "version": 1},
		Audit: &AuditEvent{At: "2026-09-11T01:00:00Z", Event: "grant_draft", Target: "draft", Note: "first"}}
	entered, release := make(chan struct{}), make(chan struct{})
	released := false
	defer func() {
		commitBoundary = func(string) {}
		if !released {
			close(release)
		}
	}()
	commitBoundary = func(phase string) {
		if phase == "grant" {
			close(entered)
			<-release
		}
	}
	winnerDone := make(chan error, 1)
	go func() {
		_, err := st.CommitGrantFrom(winner, "src", srcRev, srcDoc.Signature)
		winnerDone <- err
	}()
	<-entered

	// A reader inside the window observes the half-published commit as incomplete.
	if _, _, err := st.GetGrantWithSeq("draft"); !errors.Is(err, ErrIncompleteCommit) {
		t.Fatalf("in-flight commit must read as incomplete: %v", err)
	}

	// The duplicate committer (same draft id, different request note) must block
	// on the commit lock while the first commit is inside the window.
	duplicate := winner
	duplicate.Audit = &AuditEvent{At: "2026-09-11T01:00:01Z", Event: "grant_draft", Target: "draft", Note: "second"}
	duplicateDone := make(chan error, 1)
	go func() {
		_, err := st.CommitGrantFrom(duplicate, "src", srcRev, srcDoc.Signature)
		duplicateDone <- err
	}()
	select {
	case err := <-duplicateDone:
		t.Fatalf("duplicate finished inside the in-flight window: %v", err)
	case <-time.After(50 * time.Millisecond):
	}

	close(release)
	released = true
	if err := <-winnerDone; err != nil {
		t.Fatal("winner commit failed:", err)
	}
	if err := <-duplicateDone; !errors.Is(err, ErrRevisionConflict) {
		t.Fatalf("duplicate must conflict with the settled journal: %v", err)
	}

	// The conflict re-read now converges on the winner's committed draft.
	committed, seq, err := st.GetGrantWithSeq("draft")
	if err != nil || seq != 0 || committed.Status != "pending_approval" {
		t.Fatal(seq, err, committed)
	}
	entries, err := os.ReadDir(filepath.Join(st.Dir, "commit-audit"))
	if err != nil || len(entries) != 2 { // src.0 + draft.0
		t.Fatal("commit audit files", entries, err)
	}
	if _, err := os.Stat(filepath.Join(st.Dir, "commit-audit", "draft.0.json")); err != nil {
		t.Fatal("winner audit missing", err)
	}
}
