package intent

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"
)

func TestSharedMatcherVectors(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/contracts/intent-v2-matcher-cases.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name                 string
		ResourceConstraints  []ResourceConstraint  `json:"resource_constraints"`
		ParameterConstraints []ParameterConstraint `json:"parameter_constraints"`
		Tool                 string
		Params               map[string]any
		Allowed              bool
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if err = d.Decode(&cases); err != nil {
		t.Fatal(err)
	}
	for _, tc := range cases {
		t.Run(tc.Name, func(t *testing.T) {
			c := testContract()
			c.AllowedTools = []string{tc.Tool}
			c.AllowedEffects = []string{"file.read", "network.request", "message.send"}
			c.ResourceConstraints = tc.ResourceConstraints
			c.ParameterConstraints = tc.ParameterConstraints
			if err := c.Validate(); err != nil {
				t.Fatal(err)
			}
			err := c.Authorize("hermes", "a-1", "u-1", tc.Tool, tc.Params, time.Date(2026, 9, 7, 0, 0, 0, 0, time.UTC))
			if (err == nil) != tc.Allowed {
				t.Fatalf("allowed=%v error=%v", tc.Allowed, err)
			}
		})
	}
}
func TestExactJSONNumbers(t *testing.T) {
	atLimit := json.Number(strings.Repeat("9", 1024))
	overLimit := json.Number(strings.Repeat("9", 1025))
	if !jsonEqual(atLimit, atLimit) || jsonEqual(overLimit, overLimit) {
		t.Fatal("numeric comparison budget boundary")
	}

	for _, tc := range []struct {
		a, b  string
		equal bool
	}{
		{"1", "1.0", true}, {"-0.0", "0", true}, {"1e3", "1000", true}, {"0.001", "1e-3", true}, {"9007199254740992", "9007199254740993", false}, {"1e99999999999999999999", "10e99999999999999999998", true}, {"1", "true", false}, {"null", "0", false}, {`{"n":1}`, `{"n":1.0}`, true}, {`{"n":null}`, `{"x":null}`, false},
	} {
		t.Run(tc.a+"_"+tc.b, func(t *testing.T) {
			decode := func(s string) any {
				var v any
				d := json.NewDecoder(strings.NewReader(s))
				d.UseNumber()
				if err := d.Decode(&v); err != nil {
					t.Fatal(err)
				}
				return v
			}
			if jsonEqual(decode(tc.a), decode(tc.b)) != tc.equal {
				t.Fatal("incorrect equality")
			}
		})
	}
}
func TestShellCannotClaimExhaustiveEffects(t *testing.T) {
	c := testContract()
	c.AllowedTools = []string{"Bash"}
	c.AllowedEffects = []string{"process.exec", "network.request", "unknown"}
	for _, command := range []string{"ls", "curl\thttps://example.com", "python -c 'pass'", "echo $(cat /secret)", "cat x | tee y", "ssh host command", "sh script.sh", "echo ok > /tmp/result"} {
		assertCode(t, c.Authorize("hermes", "a-1", "u-1", "Bash", map[string]any{"command": command}, time.Now()), "runtime_effect_unknown")
	}
}
func TestProvenanceRefsAreBoundedSignedMetadata(t *testing.T) {
	bounded := testContract()
	for i := 0; i < 64; i++ {
		bounded.ProvenanceRefs = append(bounded.ProvenanceRefs, fmt.Sprintf("ref-%d", i))
	}
	if err := bounded.Validate(); err != nil {
		t.Fatal(err)
	}
	bounded.ProvenanceRefs = append(bounded.ProvenanceRefs, "ref-over-limit")
	assertCode(t, bounded.Validate(), "intent_invalid_provenance_ref")

	for _, refs := range [][]string{{"../secret"}, {"duplicate", "duplicate"}, make([]string, 65)} {
		c := testContract()
		c.ProvenanceRefs = refs
		assertCode(t, c.Validate(), "intent_invalid_provenance_ref")
	}
	s := testStore(t)
	c := testContract()
	c.ProvenanceRefs = []string{"prov-1"}
	issued, err := s.Issue(c)
	if err != nil {
		t.Fatal(err)
	}
	issued.ProvenanceRefs = []string{"prov-forged"}
	raw, _ := json.Marshal(issued)
	p, _ := s.path(c.IntentID)
	if err = os.WriteFile(p, raw, 0600); err != nil {
		t.Fatal(err)
	}
	_, err = s.Get(c.IntentID)
	assertCode(t, err, "intent_digest_mismatch")
}
