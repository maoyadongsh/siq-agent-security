package state

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestCommitGrantHappyPath(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	dp := grant.DesiredPolicy{"policy_id": "pol1", "version": 1, "backend": "openshell"}
	audit := AuditEvent{At: "2026-09-06T00:00:00Z", Event: "grant_create", Target: "g1"}
	seq, err := st.CommitGrant(GrantCommit{
		Grant:            grant.Grant{GrantID: "g1", Status: "pending"},
		ExpectedRevision: -1,
		DesiredPolicy:    dp,
		Audit:            &audit,
	})
	if err != nil {
		t.Fatal(err)
	}
	if seq != 0 {
		t.Fatalf("seq=%d", seq)
	}
	if st.HasIncompleteCommit("g1", seq) {
		t.Fatal("happy path must not leave incomplete marker")
	}
	g, err := st.GetGrant("g1")
	if err != nil || g.Status != "pending" {
		t.Fatalf("grant: %+v %v", g, err)
	}
	if _, err := os.Stat(filepath.Join(st.Dir, "policies", "pol1.v1.json")); err != nil {
		t.Fatal("desired policy missing:", err)
	}
	events, err := st.TailAudit(10)
	if err != nil || len(events) != 1 || events[0].Event != "grant_create" {
		t.Fatalf("audit=%+v err=%v", events, err)
	}
}

func TestCommitGrantPolicyFailureLeavesIncomplete(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	// Block the expected policy filename with a directory; the prepared
	// transaction must remain recoverable without publishing the grant.
	if err := os.Mkdir(filepath.Join(st.Dir, "policies", "pol2.v1.json"), 0700); err != nil {
		t.Fatal(err)
	}
	dp := grant.DesiredPolicy{"policy_id": "pol2", "version": 1}
	audit := AuditEvent{At: "2026-09-06T00:00:00Z", Event: "grant_create", Target: "g2"}
	seq, err := st.CommitGrant(GrantCommit{
		Grant:            grant.Grant{GrantID: "g2", Status: "pending"},
		ExpectedRevision: -1,
		DesiredPolicy:    dp,
		Audit:            &audit,
	})
	var inc *IncompleteCommitError
	if !errors.As(err, &inc) {
		t.Fatalf("want IncompleteCommitError, got %v", err)
	}
	if !errors.Is(err, ErrIncompleteCommit) {
		t.Fatal("errors.Is IncompleteCommit")
	}
	if inc.Phase != "desired_policy" || inc.Seq != seq || seq != 0 {
		t.Fatalf("inc=%+v seq=%d", inc, seq)
	}
	if !st.HasIncompleteCommit("g2", seq) {
		t.Fatal("incomplete marker required")
	}
	if _, err := st.GetGrant("g2"); !errors.Is(err, ErrIncompleteCommit) {
		t.Fatalf("incomplete grant must be hidden: %v", err)
	}
	events, err := st.TailAudit(10)
	if err != nil {
		t.Fatal(err)
	}
	if len(events) != 0 {
		t.Fatalf("audit must not succeed after policy failure: %+v", events)
	}
	markers, err := st.ListIncompleteCommits()
	if err != nil || len(markers) != 1 || markers[0].GrantID != "g2" || !markers[0].Recoverable {
		t.Fatalf("markers=%+v err=%v", markers, err)
	}
}

func TestCommitGrantAuditFailureLeavesIncomplete(t *testing.T) {
	dir := t.TempDir()
	st, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	dp := grant.DesiredPolicy{"policy_id": "pola", "version": 1}
	// Block the immutable transaction audit destination.
	if err := os.MkdirAll(filepath.Join(dir, "commit-audit", "g3.0.json"), 0o700); err != nil {
		t.Fatal(err)
	}
	audit := AuditEvent{At: "2026-09-06T00:00:00Z", Event: "grant_create", Target: "g3"}
	seq, err := st.CommitGrant(GrantCommit{
		Grant:            grant.Grant{GrantID: "g3", Status: "pending"},
		ExpectedRevision: -1,
		DesiredPolicy:    dp,
		Audit:            &audit,
	})
	var inc *IncompleteCommitError
	if !errors.As(err, &inc) {
		t.Fatalf("want IncompleteCommitError, got %v", err)
	}
	if inc.Phase != "audit" {
		t.Fatalf("phase=%s", inc.Phase)
	}
	if !st.HasIncompleteCommit("g3", seq) {
		t.Fatal("incomplete marker required")
	}
	if _, err := os.Stat(filepath.Join(dir, "policies", "pola.v1.json")); err != nil {
		t.Fatal("policy should have landed before audit failure:", err)
	}
}

func TestCommitGrantCASConflictDoesNotMarkIncomplete(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := st.PutGrantCAS(grant.Grant{GrantID: "g4", Status: "pending"}, -1); err != nil {
		t.Fatal(err)
	}
	_, err = st.CommitGrant(GrantCommit{
		Grant:            grant.Grant{GrantID: "g4", Status: "approved"},
		ExpectedRevision: -1,
		DesiredPolicy:    grant.DesiredPolicy{"policy_id": "p", "version": 1},
		Audit:            &AuditEvent{At: "t", Event: "x", Target: "g4"},
	})
	if !errors.Is(err, ErrRevisionConflict) {
		t.Fatalf("want revision conflict, got %v", err)
	}
	if st.HasIncompleteCommit("g4", 0) {
		t.Fatal("CAS conflict must not write incomplete marker for the failed publish")
	}
}
