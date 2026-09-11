package state

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestDerivedGrantSourceCASAndAuditFailure(t *testing.T) {
	for _, kind := range []string{"valid", "stale", "signature", "audit-failure"} {
		t.Run(kind, func(t *testing.T) {
			s, err := Open(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			source := grant.Grant{GrantID: "source", Signature: "exact-source"}
			seq, err := s.CommitGrant(GrantCommit{Grant: source, ExpectedRevision: -1})
			if err != nil {
				t.Fatal(err)
			}
			revision, sig := seq, source.Signature
			switch kind {
			case "stale":
				revision--
			case "signature":
				sig = "different"
			case "audit-failure":
				if err := os.WriteFile(filepath.Join(s.Dir, "commit-audit"), []byte("blocked"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			c := GrantCommit{Grant: grant.Grant{GrantID: "draft", Status: "pending_approval"}, ExpectedRevision: -1, Audit: &AuditEvent{Event: "grant_draft", Target: "draft"}}
			_, err = s.CommitGrantFrom(c, source.GrantID, revision, sig)
			if kind == "valid" {
				if err != nil {
					t.Fatal(err)
				}
				events, e := s.TailAudit(10)
				if e != nil || len(events) != 1 || events[0].Event != "grant_draft" {
					t.Fatal(events, e)
				}
			} else {
				if err == nil {
					t.Fatal("invalid derived commit accepted")
				}
				if _, _, readErr := s.GetGrantWithSeq("draft"); readErr == nil {
					t.Fatal("failed draft visible")
				}
				if kind != "audit-failure" && !errors.Is(err, ErrRevisionConflict) {
					t.Fatal(err)
				}
			}
			current, revision, e := s.GetGrantWithSeq("source")
			if e != nil || revision != seq || current.Signature != source.Signature {
				t.Fatal("source changed")
			}
		})
	}
}
