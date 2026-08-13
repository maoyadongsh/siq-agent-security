package main

import (
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

// TestRedactorString covers the siq.redaction.v1 rule set.
func TestRedactorString(t *testing.T) {
	r := protocol.NewRedactor()
	cases := []struct {
		in      string
		redacted bool
	}{
		{"sk-abc123def456ghi789jkl012", true},
		{"api_key=super-secret-value", true},
		{"password=hunter2", true},
		{"Authorization: Bearer abc.def.ghi", true},
		{"AKIAIOSFODNN7EXAMPLE", true},
		{"ghp_012345678901234567890123456789012345", true},
		{"-----BEGIN PRIVATE KEY-----\nabc\ndef\n-----END PRIVATE KEY-----", true},
		{"model: gpt-4o", false},
		{"hermes://profiles/siq_legal_advisor", false},
	}
	for _, tc := range cases {
		out := r.RedactString(tc.in)
		if tc.redacted && out == tc.in {
			t.Errorf("expected redaction of %q, got %q", tc.in, out)
		}
		if !tc.redacted && out != tc.in {
			t.Errorf("unexpected redaction of %q → %q", tc.in, out)
		}
	}
}

// TestRedactorRejectsEnvFile: .env content must be refused outright.
func TestRedactorRejectsEnvFile(t *testing.T) {
	r := protocol.NewRedactor()
	for _, name := range []string{".env", ".env.local", ".env.production"} {
		if _, err := r.RedactFileContent(name, []byte("SECRET=x")); err == nil {
			t.Errorf("RedactFileContent(%q) must be refused", name)
		}
	}
	out, err := r.RedactFileContent("config.yaml", []byte("api_key=secret-value"))
	if err != nil {
		t.Fatalf("config.yaml must be redactable: %v", err)
	}
	if !strings.Contains(string(out), "[REDACTED]") {
		t.Errorf("redaction not applied: %q", out)
	}
}

func TestContentHashDeterministic(t *testing.T) {
	a := protocol.ContentHash([]byte("payload"))
	b := protocol.ContentHash([]byte("payload"))
	if a != b || len(a) != 64 {
		t.Fatalf("content hash not deterministic: %q vs %q", a, b)
	}
	if protocol.ContentHash([]byte("payload-2")) == a {
		t.Error("different payloads must hash differently")
	}
}

// TestValidateBatchReferences: every evidence must be referenced by at least
// one candidate; unreferenced evidence is dropped; empty evidence_ids is a
// structural error.
func TestValidateBatchReferences(t *testing.T) {
	evA := &protocol.Evidence{EvidenceID: "ev-a"}
	evB := &protocol.Evidence{EvidenceID: "ev-b"}
	cand := &protocol.Candidate{CandidateID: "c1", EvidenceIDs: []string{"ev-a"}}

	kept, dropped, err := ValidateBatchReferences([]*protocol.Candidate{cand}, []*protocol.Evidence{evA, evB})
	if err != nil {
		t.Fatal(err)
	}
	if len(kept) != 1 || kept[0] != evA {
		t.Errorf("kept=%v, want only ev-a", kept)
	}
	if len(dropped) != 1 || dropped[0] != evB {
		t.Errorf("dropped=%v, want only ev-b", dropped)
	}

	// No candidates → everything is dropped (nothing references it).
	kept, _, err = ValidateBatchReferences(nil, []*protocol.Evidence{evA})
	if err != nil {
		t.Fatal(err)
	}
	if len(kept) != 0 {
		t.Errorf("evidence without candidates must be dropped, kept=%d", len(kept))
	}

	// Candidate without evidence_ids violates the schema (minItems:1).
	bad := &protocol.Candidate{CandidateID: "c2"}
	if _, _, err := ValidateBatchReferences([]*protocol.Candidate{bad}, nil); err == nil {
		t.Error("candidate with empty evidence_ids must be a structural error")
	}
}

// TestSignerRoundTrip: sign with the local keypair, verify with its PEM.
func TestSignerRoundTrip(t *testing.T) {
	s, err := NewSigner()
	if err != nil {
		t.Fatal(err)
	}
	pubPEM, err := s.PublicKeyPEM()
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(pubPEM, "BEGIN PUBLIC KEY") {
		t.Fatalf("public key PEM malformed: %q", pubPEM)
	}
	data := []byte("evidence package")
	sig, err := s.Sign(data)
	if err != nil {
		t.Fatal(err)
	}
	if err := VerifySignature(pubPEM, data, sig); err != nil {
		t.Fatalf("verify: %v", err)
	}
	if err := VerifySignature(pubPEM, []byte("tampered"), sig); err == nil {
		t.Fatal("tampered data must fail verification")
	}
	if err := VerifySignature("not-pem", data, sig); err == nil {
		t.Fatal("invalid PEM must fail verification")
	}
}

// TestSealEvidence: Edge-owned fields are filled and the signature is set.
func TestSealEvidence(t *testing.T) {
	s, err := NewSigner()
	if err != nil {
		t.Fatal(err)
	}
	ev := &protocol.Evidence{
		EvidenceID:    "ev:test:1",
		SourceType:    "manifest",
		SourceLocator: "test/1",
		ContentHash:   protocol.ContentHash([]byte("x")),
	}
	if err := SealEvidence(ev, s, "device-1"); err != nil {
		t.Fatal(err)
	}
	if ev.CollectorID != "device-1" {
		t.Errorf("collector_id=%q", ev.CollectorID)
	}
	if ev.CollectedAt == "" || ev.ObservedAt == "" {
		t.Error("collected_at/observed_at must be filled")
	}
	if ev.RedactionProfile != protocol.RedactionProfile {
		t.Errorf("redaction_profile=%q", ev.RedactionProfile)
	}
	if ev.Signature == "" {
		t.Fatal("signature must be set")
	}
}
