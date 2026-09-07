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

func TestFixedBindingRevocationVector(t *testing.T) {
	s := testStore(t)
	c, err := s.Issue(testContract())
	if err != nil {
		t.Fatal(err)
	}
	b := Binding{BindingID: bindingID("hermes", "vector-session", "a-1"), Platform: "hermes", SessionID: "vector-session", AgentID: "a-1", TaskID: c.TaskID, IntentID: c.IntentID, IntentDigest: c.Digest, BoundAt: "2026-09-07T15:00:00Z", ExpiresAt: c.ExpiresAt, AuthorityRevision: c.Authority.Revision}
	b.Signature, err = s.key.SignCanonical(bindingMap(b))
	if err != nil {
		t.Fatal(err)
	}
	d, err := bindingDigest(b)
	if err != nil {
		t.Fatal(err)
	}
	r := BindingRevocation{SchemaVersion: "intent-binding-revocation/v1", BindingID: b.BindingID, BindingDigest: d, RevokedAt: "2026-09-07T15:01:00Z", ReasonCode: "intent_binding_revoked", SigningSchema: "local_canonical/v1"}
	r.Signature, err = s.key.SignCanonical(revocationMap(r))
	if err != nil {
		t.Fatal(err)
	}
	canonical, err := canon.Marshal(revocationMap(r))
	if err != nil {
		t.Fatal(err)
	}
	vector := map[string]any{"binding": b, "revocation": r, "canonical_hex": hex.EncodeToString(canonical), "public_key_hex": hex.EncodeToString(s.key.Public())}
	for name, doc := range map[string]any{"intent-binding-revoke-request.v1.sample.json": map[string]string{"expected_intent_digest": b.IntentDigest}, "intent-binding-revocation.v1.sample.json": r, "intent-binding-revocation.v1.vector.json": vector} {
		raw, err := json.MarshalIndent(doc, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		raw = append(raw, '\n')
		path := filepath.Join("..", "..", "testdata", "contracts", name)
		if os.Getenv("SIQ_AGENT_SECURITY_UPDATE_SAMPLES") == "1" {
			if err = os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(expected, raw) {
			t.Fatalf("%s differs from Go canonical/signing output", name)
		}
	}
}
