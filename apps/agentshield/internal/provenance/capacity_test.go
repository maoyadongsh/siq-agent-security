package provenance

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestGraphNodeAndEdgeCapacityBoundaries(t *testing.T) {
	for _, kind := range []string{"nodes", "edges"} {
		t.Run(kind, func(t *testing.T) {
			a, i, key, now := authorityFixture(t)
			s, err := Open(t.TempDir(), key)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := s.RegisterIssuer(i); err != nil {
				t.Fatal(err)
			}
			dir := s.graphDir(a.Scope)
			if err := os.MkdirAll(dir, 0700); err != nil {
				t.Fatal(err)
			}
			// Seed complete, valid signed fixtures directly to keep a capacity test from
			// performing a quadratic number of publication scans.
			seed := func(id string, parents []string) {
				t.Helper()
				node := a
				node.ProvenanceID = id
				node.Parents = parents
				if len(parents) > 0 {
					node.Derivation = "aggregated"
				}
				node.Signature, err = key.SignCanonical(node.Unsigned())
				if err != nil {
					t.Fatal(err)
				}
				if err := publishRecord(filepath.Join(dir, id+".json"), node); err != nil {
					t.Fatal(err)
				}
			}
			candidate := a
			candidate.Signature = ""
			candidate.ProvenanceID = "at-limit"
			if kind == "nodes" {
				for n := 0; n < MaxNodes-1; n++ {
					seed(fmt.Sprintf("node-%d", n), []string{})
				}
			} else {
				parents := []string{}
				for n := 0; n < 32; n++ {
					id := fmt.Sprintf("root-%d", n)
					seed(id, []string{})
					parents = append(parents, id)
				}
				for n := 0; n < MaxEdges/32-1; n++ {
					seed(fmt.Sprintf("aggregate-%d", n), parents)
				}
				candidate.Parents = parents
				candidate.Derivation = "aggregated"
			}
			if _, err := s.IssueAssertion(candidate, now); err != nil {
				t.Fatal("exact limit rejected", err)
			}
			candidate.ProvenanceID = "over-limit"
			if kind == "edges" {
				candidate.Parents = candidate.Parents[:1]
			}
			if _, err := s.IssueAssertion(candidate, now); err == nil {
				t.Fatal("capacity exceeded")
			}
		})
	}
}
