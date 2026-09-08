package intent

import (
	"encoding/json"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/completion"
	"siq-agent-security/apps/agentshield/internal/provenance"
)

func TestEffectRequirementsSignedDualRead(t *testing.T) {
	s := testStore(t)
	c := testContract()
	c.SchemaVersion = "intent/v3"
	c.IntentID = "intent-effect"
	constraints := []provenance.Constraint{}
	c.ProvenanceConstraints = &constraints
	c.AllowedTools = []string{"write_file"}
	c.AllowedEffects = []string{"file.write"}
	r := completion.Requirement{RequirementID: "write-report", EffectType: "file.write", ResourceRef: "filesystem:sha256:" + strings.Repeat("a", 64), ExpectedDigest: strings.Repeat("b", 64), MinimumIndependence: "host_independent", MinimumCoverage: "partial"}
	reqs := []completion.Requirement{r}
	c.EffectRequirements = &reqs
	issued, err := s.Issue(c)
	if err != nil {
		t.Fatal(err)
	}
	got, err := s.Get(c.IntentID)
	if err != nil || got.EffectRequirements == nil || (*got.EffectRequirements)[0] != r || got.Signature != issued.Signature {
		t.Fatal(got, err)
	}
	changed := c
	other := r
	other.ExpectedDigest = strings.Repeat("c", 64)
	changedReqs := []completion.Requirement{other}
	changed.EffectRequirements = &changedReqs
	changedSigned, err := testStore(t).Issue(changed)
	if err != nil || changedSigned.Digest == issued.Digest {
		t.Fatal("effect requirement absent from digest", err)
	}
	c.SchemaVersion = "intent/v2"
	if c.Validate() == nil {
		t.Fatal("V2 accepted V3 effect requirements")
	}
	for _, raw := range []string{`{"schema_version":"intent/v2","effect_requirements":null}`, `{"schema_version":"intent/v2","effect_requirements":[]}`, `{"schema_version":"intent/v3","effect_requirements":null}`} {
		var out Contract
		if json.Unmarshal([]byte(raw), &out) == nil {
			t.Fatal("null/downgrade accepted", raw)
		}
	}
	c.SchemaVersion = "intent/v3"
	dup := []completion.Requirement{r, r}
	c.EffectRequirements = &dup
	if c.Validate() == nil {
		t.Fatal("duplicate requirement accepted")
	}
	tooMany := make([]completion.Requirement, 129)
	c.EffectRequirements = &tooMany
	if c.Validate() == nil {
		t.Fatal("requirement capacity exceeded")
	}
	c.EffectRequirements = &reqs
	c.AllowedEffects = []string{"file.read"}
	if c.Validate() == nil {
		t.Fatal("effect requirement expanded authority")
	}
	for _, field := range []string{"requirement_id", "effect_type", "resource_ref", "expected_digest", "minimum_independence", "minimum_coverage"} {
		raw, _ := json.Marshal(r)
		var doc map[string]any
		_ = json.Unmarshal(raw, &doc)
		delete(doc, field)
		raw, _ = json.Marshal(doc)
		var bad completion.Requirement
		if json.Unmarshal(raw, &bad) == nil {
			t.Fatal("missing requirement field accepted", field)
		}
	}
}
