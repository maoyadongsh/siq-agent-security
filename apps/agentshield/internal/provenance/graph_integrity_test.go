package provenance

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestPersistedAssertionTamperingFailsAfterRestart(t *testing.T) {
	for _, field := range []string{"content_digest", "signature"} {
		t.Run(field, func(t *testing.T) {
			a, issuer, key, now := authorityFixture(t)
			dir := t.TempDir()
			s, err := Open(dir, key)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := s.RegisterIssuer(issuer); err != nil {
				t.Fatal(err)
			}
			a.Signature = ""
			if _, err := s.IssueAssertion(a, now); err != nil {
				t.Fatal(err)
			}
			if _, err := s.Resolve(a.ProvenanceID, a.Scope, now); err != nil {
				t.Fatal("valid persisted assertion rejected", err)
			}
			path := filepath.Join(s.graphDir(a.Scope), a.ProvenanceID+".json")
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			var changed map[string]any
			if err := json.Unmarshal(raw, &changed); err != nil {
				t.Fatal(err)
			}
			changed[field] = strings.Repeat("0", len(changed[field].(string)))
			raw, err = json.Marshal(changed)
			if err != nil {
				t.Fatal(err)
			}
			// Deliberately corrupt only the private fixture's immutable record.
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
			s, err = Open(dir, key)
			if err != nil {
				t.Fatal(err)
			}
			_, err = s.Resolve(a.ProvenanceID, a.Scope, now)
			var violation *Violation
			if !errors.As(err, &violation) || violation.Code != "provenance_signature_invalid" {
				t.Fatal("persisted tampering bypassed signature verification", err)
			}
		})
	}
}
