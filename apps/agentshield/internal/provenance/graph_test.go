package provenance

import (
	"fmt"
	"testing"
	"time"
)

func TestGraphRejectsTrustAndSourceLaundering(t *testing.T) {
	a, i, key, now := authorityFixture(t)
	s, err := Open(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	i.AllowedSourceTypes = []string{"USER", "MCP", "AGENT", "UNKNOWN"}
	if _, err := s.RegisterIssuer(i); err != nil {
		t.Fatal(err)
	}
	a.Source.Type, a.Source.Trust, a.Signature = "MCP", "untrusted", ""
	root, err := s.IssueAssertion(a, now)
	if err != nil {
		t.Fatal(err)
	}
	child := a
	child.ProvenanceID = "child"
	child.Parents = []string{root.ProvenanceID}
	child.Derivation = "transformed"
	child.Source.Trust = "trusted"
	if _, err := s.IssueAssertion(child, now); err == nil {
		t.Fatal("parent trust upgraded")
	}
	child.Source.Trust = "untrusted"
	child.Source.Type = "USER"
	if _, err := s.IssueAssertion(child, now); err == nil {
		t.Fatal("MCP laundered into USER")
	}
	child.Source.Type = "AGENT"
	issued, err := s.IssueAssertion(child, now)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.ImportAssertion(issued, now); err != nil {
		t.Fatal("identical retry failed", err)
	}
	s, err = Open(s.dir, key)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.Resolve("child", a.Scope, now); err != nil {
		t.Fatal("restart lost graph", err)
	}
	wrong := a.Scope
	wrong.SessionID = "other"
	if _, err := s.Resolve("child", wrong, now); err == nil {
		t.Fatal("cross-session replay")
	}
	if _, err := s.Resolve("child", a.Scope, now.Add(time.Hour)); err == nil {
		t.Fatal("expired graph accepted")
	}
	if _, err := s.RevokeIssuer(i.IssuerID, now); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Resolve("child", a.Scope, now); err == nil {
		t.Fatal("revoked parent authority retained")
	}
}
func TestGraphDepthLimit(t *testing.T) {
	a, i, key, now := authorityFixture(t)
	s, err := Open(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.RegisterIssuer(i); err != nil {
		t.Fatal(err)
	}
	a.Signature = ""
	for n := 1; n <= MaxDepth+1; n++ {
		a.ProvenanceID = fmt.Sprintf("depth-%d", n)
		if n > 1 {
			a.Parents = []string{fmt.Sprintf("depth-%d", n-1)}
			a.Derivation = "transformed"
		}
		_, err := s.IssueAssertion(a, now)
		if n <= MaxDepth && err != nil {
			t.Fatalf("depth %d: %v", n, err)
		}
		if n > MaxDepth && err == nil {
			t.Fatal("depth exceeded")
		}
	}
}
