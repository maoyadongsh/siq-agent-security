package state

import (
	"bytes"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestPutAdmissionPersistsIndependentSkills(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	for _, rel := range []string{"malicious/env-webhook", "benign/official-like"} {
		root := filepath.Join("..", "admission", "testdata", "skills", rel)
		res, err := admission.Admit(root, admission.Options{
			Source:  admission.Source{Type: "local_dir", Locator: "testdata/skills/" + rel, TrustLevel: "unknown"},
			Version: "test",
			Key:     key,
			Pack:    pack,
		})
		if err != nil {
			t.Fatalf("%s: %v", rel, err)
		}
		if err := st.PutAdmission(res); err != nil {
			t.Fatalf("store %s: %v", rel, err)
		}
	}
	listed, err := st.ListAdmissions()
	if err != nil || len(listed) != 2 {
		t.Fatalf("admissions: %d %v", len(listed), err)
	}
}

func TestPutAdmissionIsIdempotentForSameSkill(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join("..", "admission", "testdata", "skills", "benign", "official-like")
	opts := admission.Options{
		Source:  admission.Source{Type: "local_dir", Locator: "testdata/skills/benign/official-like", TrustLevel: "unknown"},
		Version: "test",
		Key:     key,
		Pack:    pack,
	}
	first, err := admission.Admit(root, opts)
	if err != nil {
		t.Fatal(err)
	}
	if err := st.PutAdmission(first); err != nil {
		t.Fatal(err)
	}
	second, err := admission.Admit(root, opts)
	if err != nil {
		t.Fatal(err)
	}
	if err := st.PutAdmission(second); err != nil {
		t.Fatalf("re-admit of the same skill must be idempotent: %v", err)
	}
}

func TestAdmissionStoragePreservesSignatureAndStrictLegacyCompatibility(t *testing.T) {
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	k, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	pack, _ := rulepack.Builtin()
	res, err := admission.Admit(filepath.Join("..", "admission", "testdata", "skills", "benign", "official-like"), admission.Options{Key: k, Pack: pack, Version: "test"})
	if err != nil {
		t.Fatal(err)
	}
	if !admission.Verify(k.Public(), res.Admission) {
		t.Fatal("fixture not signed")
	}
	if err := s.PutAdmission(res); err != nil {
		t.Fatal(err)
	}
	stored, err := s.GetAdmission(res.Admission.AdmissionID)
	if err != nil || !admission.Verify(k.Public(), *stored) {
		t.Fatal("storage mutated signed admission", err)
	}
	legacy := *stored
	path := filepath.Join(s.Dir, "admissions", legacy.AdmissionID+".skill-card.md")
	legacy.SkillCardRef = &path
	if admission.Verify(k.Public(), legacy) {
		t.Fatal("legacy reproduction unexpectedly valid")
	}
	if !s.VerifyAdmission(k.Public(), legacy) {
		t.Fatal("known legacy projection rejected")
	}
	other := "/foreign/card.md"
	changed := legacy
	changed.SkillCardRef = &other
	if s.VerifyAdmission(k.Public(), changed) {
		t.Fatal("arbitrary path normalized")
	}
	changed = legacy
	changed.Verdict = "quarantine"
	if s.VerifyAdmission(k.Public(), changed) {
		t.Fatal("changed verdict verified")
	}
	wrong, _ := signing.FromSeed(bytes.Repeat([]byte{8}, 32))
	if s.VerifyAdmission(wrong.Public(), legacy) {
		t.Fatal("wrong key accepted")
	}
	if legacy.SkillCardRef == nil || *legacy.SkillCardRef != path {
		t.Fatal("verification mutated source")
	}
}
