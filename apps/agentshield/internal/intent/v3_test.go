package intent

import (
	"bytes"
	"encoding/json"
	"os"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"testing"
)

func TestV3ConstraintsDualReadAndSignedBinding(t *testing.T) {
	var downgrade Contract
	if json.Unmarshal([]byte(`{"schema_version":"intent/v2","provenance_constraints":null}`), &downgrade) == nil {
		t.Fatal("V2 accepted V3 field through null")
	}
	s := testStore(t)
	v2 := testContract()
	if _, err := s.Issue(v2); err != nil {
		t.Fatal(err)
	}
	v3 := testContract()
	v3.SchemaVersion = "intent/v3"
	v3.IntentID = "int-v3"
	constraints := []provenance.Constraint{{ParameterPath: "/recipient", AllowedSourceTypes: []string{"USER"}, MinimumTrust: "trusted", Required: true}}
	v3.ProvenanceConstraints = &constraints
	issued, err := s.Issue(v3)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.MarshalIndent(issued, "", "  ")
	path := "../../testdata/contracts/intent-contract.v3.sample.json"
	if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
		if err := os.WriteFile(path, append(raw, '\n'), 0644); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(bytes.TrimSpace(want), raw) {
		t.Fatal("V3 sample differs", err)
	}
	got, err := s.Get(v3.IntentID)
	if err != nil || got.Signature != issued.Signature || got.ProvenanceConstraints == nil {
		t.Fatal("V3 readback failed", err)
	}
	v2.ProvenanceConstraints = &constraints
	if v2.Validate() == nil {
		t.Fatal("V2 silently accepted V3 constraints")
	}
	v3.ProvenanceConstraints = nil
	if v3.Validate() == nil {
		t.Fatal("V3 omitted constraints")
	}
	empty := []provenance.Constraint{}
	v3.ProvenanceConstraints = &empty
	if v3.Validate() != nil {
		t.Fatal("explicit empty constraints rejected")
	}
	for _, raw := range []string{`{"parameter_path":"/recipient","allowed_source_types":["USER"],"minimum_trust":"trusted"}`, `{"parameter_path":"/recipient","allowed_source_types":["USER"],"minimum_trust":"trusted","required":null}`} {
		var c provenance.Constraint
		if json.Unmarshal([]byte(raw), &c) == nil {
			t.Fatal("missing/null required became optional")
		}
	}
}
