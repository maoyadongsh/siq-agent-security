package provenance

import (
	"fmt"
	"sync"
	"testing"
)

func TestMixedAggregationKeepsLeastTrustedParent(t *testing.T) {
	a, i, key, now := authorityFixture(t)
	s, err := Open(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	i.AllowedSourceTypes = []string{"USER", "MCP", "AGENT"}
	if _, err := s.RegisterIssuer(i); err != nil {
		t.Fatal(err)
	}
	a.Signature = ""
	if _, err := s.IssueAssertion(a, now); err != nil {
		t.Fatal(err)
	}
	b := a
	b.ProvenanceID = "mcp-parent"
	b.Source.Type = "MCP"
	b.Source.Trust = "untrusted"
	if _, err := s.IssueAssertion(b, now); err != nil {
		t.Fatal(err)
	}
	c := a
	c.ProvenanceID = "aggregate"
	c.Source.Type = "AGENT"
	c.Derivation = "aggregated"
	c.Parents = []string{a.ProvenanceID, b.ProvenanceID}
	if _, err := s.IssueAssertion(c, now); err == nil {
		t.Fatal("trusted parent concealed untrusted parent")
	}
	c.Source.Trust = "untrusted"
	if _, err := s.IssueAssertion(c, now); err != nil {
		t.Fatal(err)
	}
	got, err := s.Resolve(c.ProvenanceID, c.Scope, now)
	if err != nil || got.Source.Trust != "untrusted" {
		t.Fatal(got, err)
	}
	unknown := b
	unknown.ProvenanceID, unknown.Source.Trust, unknown.Derivation = "unknown-parent", "unknown", "unknown"
	if _, err := s.IssueAssertion(unknown, now); err != nil {
		t.Fatal(err)
	}
	c.ProvenanceID, c.Source.Trust, c.Derivation, c.Parents = "unknown-child", "unknown", "transformed", []string{unknown.ProvenanceID}
	if _, err := s.IssueAssertion(c, now); err == nil {
		t.Fatal("unknown lineage became known transformation")
	}
}
func TestConcurrentIssueResolveAndTerminalRevocation(t *testing.T) {
	a, i, key, now := authorityFixture(t)
	s, err := Open(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.RegisterIssuer(i); err != nil {
		t.Fatal(err)
	}
	a.Signature = ""
	if _, err := s.IssueAssertion(a, now); err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	for n := 0; n < 12; n++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			b := a
			b.ProvenanceID = fmt.Sprintf("concurrent-%d", n)
			b.Derivation = "transformed"
			b.Parents = []string{a.ProvenanceID}
			if _, err := s.IssueAssertion(b, now); err != nil {
				t.Error(err)
				return
			}
			if _, err := s.Resolve(b.ProvenanceID, b.Scope, now); err != nil {
				t.Error(err)
			}
		}(n)
	}
	wg.Wait()
	done := make(chan struct{})
	wg.Add(1)
	go func() {
		defer wg.Done()
		if _, err := s.RevokeIssuer(i.IssuerID, now); err != nil {
			t.Error(err)
		}
		close(done)
	}()
	for n := 0; n < 12; n++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			<-done
			if _, err := s.Resolve(fmt.Sprintf("concurrent-%d", n), a.Scope, now); err == nil {
				t.Error("post-revocation cached authority accepted")
			}
		}(n)
	}
	wg.Wait()
}
