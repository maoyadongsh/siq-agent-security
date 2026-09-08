package provenance

import (
	"testing"
	"time"
)

func TestDeterministicMCPSelectionAndParameterMatch(t *testing.T) {
	a, _, key, now := authorityFixture(t)
	s, err := Open(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	result := map[string]any{"structuredContent": map[string]any{"recipient": "alice@example.test", "note": "untrusted-text"}}
	parent, err := s.Report("mcp-result", Source{Type: "MCP", SourceID: "server/endpoint/tool"}, a.Scope, result, now.Add(time.Hour), now)
	if err != nil {
		t.Fatal(err)
	}
	selected, err := s.Select(parent.ProvenanceID, "/structuredContent/recipient", a.Scope, result, now)
	if err != nil {
		t.Fatal(err)
	}
	if selected.Source.Type != "MCP" || selected.Source.Trust != "untrusted" || selected.Derivation != "transformed" || len(selected.Parents) != 1 {
		t.Fatal("selection lost source", selected)
	}
	retry, err := s.Select(parent.ProvenanceID, "/structuredContent/recipient", a.Scope, result, now.Add(time.Second))
	if err != nil || retry.Signature != selected.Signature {
		t.Fatal("selection retry changed proof", err)
	}
	bindings := []ParameterBinding{{ParameterPath: "/recipient", ProvenanceRefs: []string{selected.ProvenanceID}}}
	constraints := []Constraint{{ParameterPath: "/recipient", AllowedSourceTypes: []string{"USER"}, MinimumTrust: "trusted", Required: true}}
	params := map[string]any{"recipient": "alice@example.test"}
	if err := s.MatchParameters(params, bindings, constraints, a.Scope, now); err == nil {
		t.Fatal("MCP selection acquired USER authority")
	}
	constraints[0].AllowedSourceTypes = []string{"MCP"}
	constraints[0].MinimumTrust = "untrusted"
	if err := s.MatchParameters(params, bindings, constraints, a.Scope, now); err != nil {
		t.Fatal("explicitly permitted source rejected", err)
	}
	forged := map[string]any{"structuredContent": map[string]any{"recipient": "attacker@example.test"}}
	if _, err := s.Select(parent.ProvenanceID, "/structuredContent/recipient", a.Scope, forged, now); err == nil {
		t.Fatal("original content substituted")
	}
	if _, err := s.Select(parent.ProvenanceID, "/missing", a.Scope, result, now); err == nil {
		t.Fatal("missing field manufactured")
	}
	if _, err := s.RevokeIssuer(parent.Issuer, now); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Select(parent.ProvenanceID, "/structuredContent/recipient", a.Scope, result, now); err == nil {
		t.Fatal("revoked parent produced child")
	}
}
