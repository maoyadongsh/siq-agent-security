package main

import (
	"bytes"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

// TestRedactorString covers the siq.redaction.v1 rule set.
func TestSignerSeedRoundTrip(t *testing.T) {
	// 密钥持久化：seed 导出/恢复后公钥一致，证据签名跨重启稳定
	s1, err := NewSigner()
	if err != nil {
		t.Fatal(err)
	}
	s2, err := NewSignerFromSeed(s1.SeedB64())
	if err != nil {
		t.Fatal(err)
	}
	pub1, _ := s1.PublicKeyPEM()
	pub2, _ := s2.PublicKeyPEM()
	if pub1 != pub2 {
		t.Fatal("seed round trip changed public key")
	}
	sig1, _ := s1.Sign([]byte("evidence-bytes"))
	sig2, _ := s2.Sign([]byte("evidence-bytes"))
	if sig1 != sig2 {
		t.Fatal("seed round trip changed signature")
	}
}

func TestCanonicalSignatureMatchesPythonFixture(t *testing.T) {
	signer, err := NewSignerFromSeed("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")
	if err != nil {
		t.Fatal(err)
	}
	payload := map[string]any{
		"task_id": "tsk_fixture",
		"note":    "<安全>",
		"counts":  []int{1, 2},
		"nested":  map[string]any{"z": false, "a": "值"},
	}
	encoded, err := CanonicalJSON(payload)
	if err != nil {
		t.Fatal(err)
	}
	expectedJSON := `{"counts":[1,2],"nested":{"a":"值","z":false},"note":"<安全>","task_id":"tsk_fixture"}`
	if string(encoded) != expectedJSON {
		t.Fatalf("canonical JSON mismatch:\nwant %s\n got %s", expectedJSON, encoded)
	}
	signature, err := signer.Sign(encoded)
	if err != nil {
		t.Fatal(err)
	}
	expectedSignature := "d9f7636415eca6419c6613673089f00cc254598d5211b710614c602d75de563e" +
		"4f32da23213289be855a998d53380b21af99c810258b57e01ff15fafe41abe04"
	if signature != expectedSignature {
		t.Fatalf("signature mismatch:\nwant %s\n got %s", expectedSignature, signature)
	}
}

func TestNewSignerFromSeedRejectsBadInput(t *testing.T) {
	if _, err := NewSignerFromSeed("not-base64!!"); err == nil {
		t.Fatal("invalid seed accepted")
	}
	if _, err := NewSignerFromSeed("c2hvcnQ="); err == nil { // 4 字节短 seed
		t.Fatal("short seed accepted")
	}
}

func TestRedactorString(t *testing.T) {
	r := protocol.NewRedactor()
	cases := []struct {
		in       string
		redacted bool
	}{
		{"sk-abc123def456ghi789jkl012", true},
		{"api_key=super-secret-value", true},
		{"password=hunter2", true},
		{"Authorization: Bearer abc.def.ghi", true},
		{"AKIAIOSFODNN7EXAMPLE", true},
		{"ghp_0123456789abcdefghijklmnopqrstuvwxyz", true}, // 测试夹具假令牌，.gitleaks.toml 已精确放行
		{"-----BEGIN PRIVATE KEY-----\nabc\ndef\n-----END PRIVATE KEY-----", true},
		{"/bin/app --password spacesecret999", true},
		{"/bin/app --token=tokensecret1234", true},
		{"https://user:passw0rd@example.com/x", true},
		{`/bin/svc --token 'quotedtok123'`, true},
		{"model: gpt-4o", false},
		{"hermes://profiles/siq_legal_advisor", false},
		{"/usr/bin/rsync -a /data /backup", false},
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
		TenantID:      "attacker-tenant",
		EnvironmentID: "attacker-environment",
		SourceType:    "manifest",
		SourceLocator: "test/1",
		ContentHash:   protocol.ContentHash([]byte("x")),
		CollectorID:   "attacker-collector",
	}
	if err := SealEvidence(ev, s, "device-1"); err != nil {
		t.Fatal(err)
	}
	if ev.CollectorID != "device-1" {
		t.Errorf("collector_id=%q", ev.CollectorID)
	}
	if ev.TenantID != "" || ev.EnvironmentID != "" {
		t.Errorf("connector-controlled tenancy fields were retained: tenant=%q environment=%q", ev.TenantID, ev.EnvironmentID)
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
	if ev.SigningSchema != EvidenceSigningSchemaV1 {
		t.Fatalf("writer must embed signing_schema=%s, got %q", EvidenceSigningSchemaV1, ev.SigningSchema)
	}
	pubPEM, err := s.PublicKeyPEM()
	if err != nil {
		t.Fatal(err)
	}
	clone := *ev
	clone.Signature = ""
	payload, err := CanonicalJSON(&clone)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(payload, []byte(`"signing_schema":"evidence_utf8/v1"`)) {
		t.Fatalf("canonical bytes must include embedded schema, got %s", payload)
	}
	if err := VerifySignature(pubPEM, payload, ev.Signature); err != nil {
		t.Fatalf("canonical evidence signature did not verify: %v", err)
	}
	// Stripping schema must invalidate the writer signature (field is in signed body).
	stripped := *ev
	stripped.Signature = ""
	stripped.SigningSchema = ""
	strippedPayload, err := CanonicalJSON(&stripped)
	if err != nil {
		t.Fatal(err)
	}
	if err := VerifySignature(pubPEM, strippedPayload, ev.Signature); err == nil {
		t.Fatal("signature must not verify after stripping signing_schema")
	}
}
