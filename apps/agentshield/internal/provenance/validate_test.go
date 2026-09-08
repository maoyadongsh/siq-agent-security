package provenance

import (
	"encoding/json"
	"testing"
)

func TestDecisionReportsCannotElevateSourceAuthority(t *testing.T) {
	allowed := map[string]bool{"MCP": true, "WEB": true, "TOOL": true, "AGENT": true, "UNKNOWN": true}
	for source := range sourceTypes {
		for trust := range trustRanks {
			err := ValidateReport(Source{Type: source, SourceID: "fixture-source", Trust: trust})
			want := allowed[source] && (trust == "unknown" || trust == "untrusted")
			if (err == nil) != want {
				t.Fatalf("source=%s trust=%s: %v", source, trust, err)
			}
		}
	}
	for _, s := range []Source{{Type: "MCP", Trust: "untrusted"}, {Type: "CUSTOM", SourceID: "x", Trust: "untrusted"}, {Type: "USER", SourceID: "x", Trust: "authoritative"}, {Type: "TRUSTED_IAM", SourceID: "x", Trust: "authoritative"}} {
		if ValidateReport(s) == nil {
			t.Fatal("forged source accepted", s)
		}
	}
}
func TestPointerBindingsAreExactAndUnambiguous(t *testing.T) {
	value := map[string]any{"a/b": []any{map[string]any{"~recipient": "user@example.test"}}, "": true}
	got, ok := PointerValue(value, "/a~1b/0/~0recipient")
	if !ok || got != "user@example.test" {
		t.Fatal(got, ok)
	}
	if got, ok := PointerValue(value, "/"); !ok || got != true {
		t.Fatal("empty key is legal JSON Pointer")
	}
	for _, p := range []string{"", "a/b", "/a~2b", "/a~1b/00/~0recipient", "/a~1b/-1", "/a~1b/+0", "/a~1b/-", "/a~1b/1", "/missing"} {
		if _, ok := PointerValue(value, p); ok {
			t.Fatal("ambiguous pointer accepted", p)
		}
	}
}
func TestContentDigestUsesCanonicalTypedValues(t *testing.T) {
	a, err := ContentDigest(map[string]any{"b": json.Number("2"), "a": "recipient"})
	if err != nil {
		t.Fatal(err)
	}
	b, err := ContentDigest(map[string]any{"a": "recipient", "b": json.Number("2")})
	if err != nil || a != b {
		t.Fatal("map order changed digest")
	}
	c, _ := ContentDigest(map[string]any{"a": "recipient", "b": "2"})
	if a == c {
		t.Fatal("value type lost in digest")
	}
	if _, err := ContentDigest(make(chan int)); err == nil {
		t.Fatal("non-JSON value accepted")
	}
}
func TestConstraintTaxonomyIsClosed(t *testing.T) {
	c := Constraint{ParameterPath: "/recipient", AllowedSourceTypes: []string{"USER"}, MinimumTrust: "authoritative", Required: true}
	if err := c.Validate(); err != nil {
		t.Fatal(err)
	}
	for _, edit := range []func(*Constraint){func(c *Constraint) { c.MinimumTrust = "trust-me" }, func(c *Constraint) { c.ParameterPath = "/bad~x" }, func(c *Constraint) { c.AllowedSourceTypes = []string{"USER", "USER"} }, func(c *Constraint) { c.AllowedSourceTypes = []string{"CUSTOM"} }} {
		bad := c
		edit(&bad)
		if bad.Validate() == nil {
			t.Fatal("invalid constraint accepted", bad)
		}
	}
}
