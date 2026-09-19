package state

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestPrivateEvidenceRetryPreservesLongerExistingRecord(t *testing.T) {
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	doc := map[string]any{"evidence_id": "retry", "content_hash": "same", "source_locator": "local", "detail": "long original observation"}
	if err := s.PutEvidence("retry", doc); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(s.Dir, "evidence", "retry.json")
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	delete(doc, "detail")
	if err := s.PutEvidence("retry", doc); err != nil {
		t.Fatalf("same identity with shorter metadata must be idempotent: %v", err)
	}
	doc["content_hash"] = "different"
	if err := s.PutEvidence("retry", doc); !errors.Is(err, ErrConflict) {
		t.Fatalf("different identity: want conflict, got %v", err)
	}
	for _, write := range []func(string, []byte) error{writeNew, writeDurable} {
		if err := write(path, []byte("x")); !errors.Is(err, ErrConflict) {
			t.Fatalf("shorter different bytes: want conflict, got %v", err)
		}
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(before, after) {
		t.Fatalf("immutable record changed: %v", err)
	}
}
