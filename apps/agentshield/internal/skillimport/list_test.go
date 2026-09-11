package skillimport

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestImportListMetadataBoundaryAndDamageIsolation(t *testing.T) {
	s, req := storeFixture(t)
	rec, _, _, err := s.Create(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	firstBytes, err := os.ReadFile(s.record(req.ImportID))
	if err != nil {
		t.Fatal(err)
	}
	second := req
	second.ImportID = "si-" + strings.Repeat("b", 32)
	if _, _, _, err := s.Create(context.Background(), second); err != nil {
		t.Fatal(err)
	}
	list, err := s.List(context.Background())
	if err != nil || len(list.Items) != 2 || list.Items[0].ImportID != second.ImportID {
		t.Fatal("order", err, list)
	}
	put(t, filepath.Join(s.blob(req.ImportID), "payload", "SKILL.md"), []byte("tampered payload"), 0600)
	put(t, s.record(second.ImportID), []byte(`{"actor_id":"UNVERIFIED_SECRET"}`), 0600)
	list, err = s.List(context.Background())
	if err != nil || len(list.Items) != 2 {
		t.Fatal(err, list)
	}
	first, bad := list.Items[0], list.Items[1]
	if first.ImportID != rec.ImportID || first.RecordStatus != "metadata_verified" || first.PayloadStatus != "unchecked" || first.Summary.FileCount != len(rec.Files) {
		t.Fatal("metadata claims content verification", first)
	}
	if bad.ImportID != second.ImportID || bad.Summary != nil || bad.RecordStatus != "unavailable" {
		t.Fatal("unverified metadata displayed", bad)
	}
	raw, _ := json.Marshal(list)
	if bytes.Contains(raw, []byte("UNVERIFIED_SECRET")) || bytes.Contains(raw, []byte(req.Path)) || bytes.Contains(raw, []byte("SKILL.md")) {
		t.Fatal("list exposed content")
	}
	after, err := os.ReadFile(s.record(req.ImportID))
	if err != nil || !bytes.Equal(firstBytes, after) {
		t.Fatal("list mutated signed record", err)
	}
	if _, _, err := s.Load(context.Background(), req.ImportID); !errors.Is(err, ErrChanged) {
		t.Fatal("full read did not catch tamper", err)
	}
}
func TestImportListBudgetsAndCanceledEmptyList(t *testing.T) {
	s, _ := storeFixture(t)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := s.List(ctx); !errors.Is(err, context.Canceled) {
		t.Fatal("empty canceled list", err)
	}
	for i := 0; i < 128; i++ {
		put(t, filepath.Join(s.dir, "records", fmt.Sprintf(".import-%03d", i)), []byte("partial"), 0600)
	}
	if list, err := s.List(context.Background()); err != nil || len(list.Items) != 0 {
		t.Fatal("published temporary record", err)
	}
	put(t, filepath.Join(s.dir, "records", ".import-over"), []byte("partial"), 0600)
	if _, err := s.List(context.Background()); !errors.Is(err, ErrLimit) {
		t.Fatal("entry budget", err)
	}
	t.Run("record_count", func(t *testing.T) {
		s, _ := storeFixture(t)
		for i := 0; i < 64; i++ {
			put(t, s.record(fmt.Sprintf("si-%032x", i)), []byte("invalid"), 0600)
		}
		if list, err := s.List(context.Background()); err != nil || len(list.Items) != 64 {
			t.Fatal(err)
		}
		put(t, s.record(fmt.Sprintf("si-%032x", 64)), []byte("invalid"), 0600)
		if _, err := s.List(context.Background()); !errors.Is(err, ErrLimit) {
			t.Fatal(err)
		}
	})
	t.Run("unexpected_file", func(t *testing.T) {
		s, _ := storeFixture(t)
		put(t, filepath.Join(s.dir, "records", "unexpected.json"), []byte("invalid"), 0600)
		if _, err := s.List(context.Background()); !errors.Is(err, ErrChanged) {
			t.Fatal(err)
		}
	})
}
func TestImportListContractSample(t *testing.T) {
	s, req := storeFixture(t)
	if _, _, _, err := s.Create(context.Background(), req); err != nil {
		t.Fatal(err)
	}
	put(t, s.record("si-"+strings.Repeat("b", 32)), []byte("invalid"), 0600)
	result, err := s.List(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	result.Items[0].Summary.CreatedAt = "2026-09-10T01:00:00Z"
	raw, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	raw = append(raw, '\n')
	path := "../../testdata/contracts/local-skill-import-list.v1.sample.json"
	if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
		if err := os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	expected, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(raw, expected) {
		t.Fatal("list sample mismatch", err)
	}
}
