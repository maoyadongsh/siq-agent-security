package provenance

import (
	"errors"
	"testing"
)

func TestSameValueDifferentProvenance(t *testing.T) {
	a, i, key, now := authorityFixture(t)
	s, err := Open(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	i.AllowedSourceTypes = []string{"USER", "MCP"}
	if _, err := s.RegisterIssuer(i); err != nil {
		t.Fatal(err)
	}
	a.Signature = ""
	user, err := s.IssueAssertion(a, now)
	if err != nil {
		t.Fatal(err)
	}
	a.ProvenanceID = "mcp-1"
	a.Source.Type, a.Source.Trust = "MCP", "untrusted"
	mcp, err := s.IssueAssertion(a, now)
	if err != nil {
		t.Fatal(err)
	}
	params := map[string]any{"recipient": "recipient@example.test"}
	constraints := []Constraint{{ParameterPath: "/recipient", AllowedSourceTypes: []string{"USER"}, MinimumTrust: "trusted", Required: true}}
	check := func(refs []string, want string) {
		t.Helper()
		binding := []ParameterBinding{{ParameterPath: "/recipient", ProvenanceRefs: refs}}
		err := s.MatchParameters(params, binding, constraints, a.Scope, now)
		if want == "" {
			if err != nil {
				t.Fatal(err)
			}
			return
		}
		var v *Violation
		if !errors.As(err, &v) || v.Code != want {
			t.Fatalf("got %v want %s", err, want)
		}
	}
	check([]string{user.ProvenanceID}, "")
	check([]string{mcp.ProvenanceID}, "provenance_source_not_allowed")
	check([]string{user.ProvenanceID, mcp.ProvenanceID}, "provenance_source_not_allowed")
	check([]string{user.ProvenanceID, "missing"}, "provenance_scope_mismatch")
	for _, boundary := range []string{"task", "session"} {
		other := a.Scope
		if boundary == "task" {
			other.TaskID = "other-task"
		} else {
			other.SessionID = "other-session"
		}
		err := s.MatchParameters(params, []ParameterBinding{{ParameterPath: "/recipient", ProvenanceRefs: []string{user.ProvenanceID}}}, constraints, other, now)
		var violation *Violation
		if !errors.As(err, &violation) || violation.Code != "provenance_scope_mismatch" {
			t.Fatal("reference escaped scope", boundary, err)
		}
	}
	check([]string{user.ProvenanceID, user.ProvenanceID}, "provenance_authority_invalid")
	params["recipient"] = "attacker@example.test"
	check([]string{user.ProvenanceID}, "provenance_content_mismatch")
	if err := s.MatchParameters(params, nil, constraints, a.Scope, now); err == nil {
		t.Fatal("missing required provenance accepted")
	}
}
func TestOptionalConstraintDoesNotIgnoreInvalidSuppliedReference(t *testing.T) {
	a, i, key, now := authorityFixture(t)
	s, err := Open(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.RegisterIssuer(i); err != nil {
		t.Fatal(err)
	}
	c := []Constraint{{ParameterPath: "/recipient", AllowedSourceTypes: []string{"USER"}, MinimumTrust: "trusted"}}
	if err := s.MatchParameters(map[string]any{}, nil, c, a.Scope, now); err != nil {
		t.Fatal("optional absent field rejected", err)
	}
	b := []ParameterBinding{{ParameterPath: "/recipient", ProvenanceRefs: []string{"forged"}}}
	if err := s.MatchParameters(map[string]any{"recipient": "value"}, b, nil, a.Scope, now); err == nil {
		t.Fatal("unconstrained forged reference ignored")
	}
}
