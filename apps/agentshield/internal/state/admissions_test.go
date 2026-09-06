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
