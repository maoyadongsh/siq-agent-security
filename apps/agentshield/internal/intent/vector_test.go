package intent

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/canon"
	"testing"
)

func TestFixedIntentVector(t *testing.T) {
	s := testStore(t)
	c := testContract()
	c.ProvenanceRefs = []string{"prov-approved-input"}
	c.ParameterConstraints = []ParameterConstraint{{Path: "/request/body/project_id", Operator: "equals", Value: "project-1"}}
	issued, err := s.Issue(c)
	if err != nil {
		t.Fatal(err)
	}
	canonical, err := canon.Marshal(unsignedMap(*issued))
	if err != nil {
		t.Fatal(err)
	}
	vector := map[string]any{"contract": issued, "canonical_hex": hex.EncodeToString(canonical), "public_key_hex": hex.EncodeToString(s.key.Public())}
	for name, doc := range map[string]any{"intent-contract.v2.sample.json": issued, "intent-contract.v2.vector.json": vector} {
		raw, err := json.MarshalIndent(doc, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		raw = append(raw, '\n')
		p := filepath.Join("..", "..", "testdata", "contracts", name)
		if os.Getenv("SIQ_AGENT_SECURITY_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(p, raw, 0600); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(p)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(raw, expected) {
			t.Fatalf("%s differs from runtime output", name)
		}
	}
}
