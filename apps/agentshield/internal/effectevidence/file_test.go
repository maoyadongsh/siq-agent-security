package effectevidence_test

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/evidencetest"
	"siq-agent-security/apps/agentshield/internal/linktest"
)

func TestActualFileWriteAndFakeSuccess(t *testing.T) {
	f := evidencetest.New(t)
	path := filepath.Join(t.TempDir(), "report.txt")
	before, err := f.Capture(path, 1024)
	if err != nil || before.Exists {
		t.Fatal(before, err)
	}
	content := []byte("synthetic confidential report")
	sum := sha256.Sum256(content)
	expected := hex.EncodeToString(sum[:])
	absent, err := f.Capture(path, 1024)
	if err != nil {
		t.Fatal(err)
	}
	fake, err := effectevidence.FileWrite(before, absent, expected)
	if err != nil || fake.Result == "expected" || fake.ExecutionState == "completed" {
		t.Fatal("tool success manufactured file effect", fake, err)
	}
	key := f.Key
	a := effectevidence.Action{ActionID: "action-file", DecisionReceiptID: "receipt-file", TaskID: "task-file", IssuedAt: time.Now().Add(-time.Minute), Authorized: true, Effects: []string{"file.write"}, Resources: f.Resources(t, path)}
	if err = os.WriteFile(path, content, 0600); err != nil {
		t.Fatal(err)
	}
	after, err := f.Capture(path, 1024)
	if err != nil || !after.Exists || after.Digest != expected || after.Size != int64(len(content)) {
		t.Fatal(after, err)
	}
	observed, err := effectevidence.FileWrite(before, after, expected)
	if err != nil || observed.Result != "expected" || observed.ExecutionState != "completed" {
		t.Fatal(observed, err)
	}
	source := effectevidence.Source{Type: "host_observer", SourceID: "file-observer", Independence: "host_independent"}
	e, err := observed.Evidence("file-1", a, source)
	if err != nil {
		t.Fatal(err)
	}
	s := f.Store
	r, err := s.Submit(e, a, source, time.Now())
	if err != nil || r.Evidence.Result != "expected" || r.Evidence.Coverage != "partial" {
		t.Fatal(r, err)
	}
	raw, _ := json.Marshal(observed)
	if strings.Contains(string(raw), path) || strings.Contains(string(raw), string(content)) {
		t.Fatal("observation leaked raw data")
	}
	unchanged, err := effectevidence.FileWrite(after, after, expected)
	if err != nil || unchanged.Result != "unknown" {
		t.Fatal("unchanged file proves execution", unchanged, err)
	}
	wrong, err := effectevidence.FileWrite(before, after, strings.Repeat("a", 64))
	if err != nil || wrong.Result != "unexpected" {
		t.Fatal(wrong, err)
	}
	materialRecord, err := s.SubmitFile("file-material", observed, a, source, time.Now())
	if err != nil || materialRecord.FileObservation == nil || *materialRecord.FileObservation != observed {
		t.Fatal(materialRecord, err)
	}
	materialRetry, err := s.SubmitFile("file-material", observed, a, source, time.Now())
	if err != nil || materialRetry.Signature != materialRecord.Signature {
		t.Fatal("file retry changed record", err)
	}
	plain := materialRecord.Evidence
	plain.Signature = ""
	if _, err = s.Submit(plain, a, source, time.Now()); !errors.Is(err, effectevidence.ErrConflict) {
		t.Fatal("material removed on retry", err)
	}
	reloaded, err := s.Get("file-material", time.Now())
	if err != nil || reloaded.FileObservation == nil {
		t.Fatal(reloaded, err)
	}
	// Even a valid outer signature cannot bind different observation material
	// to the existing inner evidence digest.
	reloaded.FileObservation.After.Size++
	reloaded.Signature, err = key.SignCanonical(unsignedRecord(t, reloaded))
	if err != nil {
		t.Fatal(err)
	}
	altered, _ := json.Marshal(reloaded)
	if err = os.WriteFile(filepath.Join(f.Dir, "effect-evidence", "file-material.json"), altered, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Get("file-material", time.Now()); !errors.Is(err, effectevidence.ErrState) {
		t.Fatal("unbound material accepted", err)
	}
	a.Authorized = false
	e.EvidenceID = "file-denied"
	r, err = s.Submit(e, a, source, time.Now())
	if err != nil || r.FindingCode != "unauthorized_effect_observed" {
		t.Fatal(r, err)
	}
}

func TestFileCaptureBoundsAndUnsafeTargets(t *testing.T) {
	f := evidencetest.New(t)
	dir := t.TempDir()
	file := filepath.Join(dir, "data")
	if err := os.WriteFile(file, []byte("1234"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := f.Capture(file, 4); err != nil {
		t.Fatal(err)
	}
	if _, err := f.Capture(file, 3); err == nil {
		t.Fatal("oversize file accepted")
	}
	for _, p := range []string{dir, "relative", filepath.Join(dir, "missing-parent", "data")} {
		if _, err := f.Capture(p, 4); err == nil {
			t.Fatal("unsafe target accepted", p)
		}
	}
	t.Run("leaf-symlink", func(t *testing.T) {
		link := filepath.Join(dir, "link")
		linktest.Symlink(t, file, link)
		if _, err := f.Capture(link, 4); err == nil {
			t.Fatal("symlink accepted")
		}
	})
	t.Run("redirected-parent", func(t *testing.T) {
		parent := filepath.Join(dir, "parent-link")
		if err := linktest.Directory(dir, parent); err != nil {
			t.Fatal(err)
		}
		defer os.Remove(parent)
		if _, err := f.Capture(filepath.Join(parent, "data"), 4); err == nil {
			t.Fatal("redirected ancestor accepted")
		}
	})
	before, err := f.Capture(file, 4)
	if err != nil {
		t.Fatal(err)
	}
	bad := before
	bad.CapturedAt = time.Now().Add(-time.Hour).UTC().Format(time.RFC3339Nano)
	if _, err := effectevidence.FileWrite(before, bad, before.Digest); err == nil {
		t.Fatal("reversed observation accepted")
	}
}

func unsignedRecord(t *testing.T, r effectevidence.Record) map[string]any {
	t.Helper()
	raw, err := json.Marshal(r)
	if err != nil {
		t.Fatal(err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	delete(doc, "signature")
	return doc
}
