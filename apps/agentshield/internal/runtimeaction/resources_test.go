package runtimeaction

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

func TestResourceRefsNormalizeWithoutPlaintext(t *testing.T) {
	for _, tc := range []struct {
		tool string
		a, b map[string]any
	}{
		{"read_file", map[string]any{"path": "/private/a/../report"}, map[string]any{"file_path": "/private/report"}},
		{"web_fetch", map[string]any{"url": "https://EXAMPLE.COM./private?token=secret"}, map[string]any{"host": "example.com"}},
		{"web_fetch", map[string]any{"url": "https://[2001:0db8::1]/"}, map[string]any{"host": "2001:db8::1"}},
	} {
		a, e1 := ExtractResources(tc.tool, tc.a)
		b, e2 := ExtractResources(tc.tool, tc.b)
		if e1 != nil || e2 != nil {
			t.Fatal(e1, e2)
		}
		refs := ResourceRefs(a)
		if !reflect.DeepEqual(refs, ResourceRefs(b)) {
			t.Fatal("equivalent resources differ")
		}
		raw, _ := json.Marshal(refs)
		for _, secret := range []string{"private", "secret", "example.com", "2001"} {
			if strings.Contains(string(raw), secret) {
				t.Fatalf("resource plaintext leaked: %s", raw)
			}
		}
	}
}
func TestInvalidResourceCannotProducePartialReferences(t *testing.T) {
	for _, params := range []map[string]any{{"path": "relative"}, {"path": "/valid", "file_path": 42}, {"path": "/valid", "file_path": "/a\x00b"}, {"path": `C:\secret`}} {
		resources, err := ExtractResources("read_file", params)
		if err == nil || len(resources) != 0 {
			t.Fatal(resources, err)
		}
	}
	for _, host := range []string{"https://user:password@example.com", "example..com", "-example.com", "example_.com", "ｅxample.com", "example.com:443", "https://example.com:bad"} {
		if _, err := NormalizeHost(host); err == nil {
			t.Fatalf("accepted %q", host)
		}
	}
}
func TestActionIDBindsResourcePrincipalAndProvenance(t *testing.T) {
	base := Envelope{Tool: "read_file", Principal: &Principal{Type: "user", ID: "u-1"}, ProvenanceRefs: []string{"prov-1"}, ResourceRefs: []ResourceRef{{Domain: "filesystem", Digest: strings.Repeat("a", 64)}}}
	for _, edit := range []func(*Envelope){func(e *Envelope) { e.Principal = &Principal{Type: "user", ID: "other"} }, func(e *Envelope) { e.ProvenanceRefs = []string{"other"} }, func(e *Envelope) {
		e.ResourceRefs = []ResourceRef{{Domain: "filesystem", Digest: strings.Repeat("b", 64)}}
	}} {
		changed := base
		edit(&changed)
		if ActionID(base) == ActionID(changed) {
			t.Fatal("identity omitted security metadata")
		}
	}
}

func TestHostLengthBoundaries(t *testing.T) {
	for _, host := range []string{strings.Repeat("a", 63), strings.Repeat(strings.Repeat("a", 63)+".", 3) + strings.Repeat("b", 61)} {
		if _, err := NormalizeHost(host); err != nil {
			t.Fatal(err)
		}
		if _, err := NormalizeHost(host + "a"); err == nil {
			t.Fatal("oversized hostname accepted")
		}
	}
}
