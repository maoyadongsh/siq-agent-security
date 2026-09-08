package effectevidence

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func TestActualFileWriteAndFakeSuccess(t *testing.T) {
	path := filepath.Join(t.TempDir(), "report.txt")
	before, err := CaptureFile(path, 1024)
	if err != nil || before.Exists {
		t.Fatal(before, err)
	}
	content := []byte("synthetic confidential report")
	sum := sha256.Sum256(content)
	expected := hex.EncodeToString(sum[:])
	absent, err := CaptureFile(path, 1024)
	if err != nil {
		t.Fatal(err)
	}
	fake, err := FileWrite(before, absent, expected)
	if err != nil || fake.Result == "expected" || fake.ExecutionState == "completed" {
		t.Fatal("tool success manufactured file effect", fake, err)
	}
	_, key, _ := fixture(t)
	a := Action{ActionID: "action-file", DecisionReceiptID: "receipt-file", TaskID: "task-file", IssuedAt: time.Now().Add(-time.Minute), Authorized: true, Effects: []string{"file.write"}, Resources: runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "filesystem", Value: path}})}
	if err = os.WriteFile(path, content, 0600); err != nil {
		t.Fatal(err)
	}
	after, err := CaptureFile(path, 1024)
	if err != nil || !after.Exists || after.Digest != expected || after.Size != int64(len(content)) {
		t.Fatal(after, err)
	}
	observed, err := FileWrite(before, after, expected)
	if err != nil || observed.Result != "expected" || observed.ExecutionState != "completed" {
		t.Fatal(observed, err)
	}
	source := Source{Type: "host_observer", SourceID: "file-observer", Independence: "host_independent"}
	e, err := observed.Evidence("file-1", a, source)
	if err != nil {
		t.Fatal(err)
	}
	s, err := NewStore(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	r, err := s.Submit(e, a, source, time.Now())
	if err != nil || r.Evidence.Result != "expected" || r.Evidence.Coverage != "partial" {
		t.Fatal(r, err)
	}
	raw, _ := json.Marshal(observed)
	if strings.Contains(string(raw), path) || strings.Contains(string(raw), string(content)) {
		t.Fatal("observation leaked raw data")
	}
	unchanged, err := FileWrite(after, after, expected)
	if err != nil || unchanged.Result != "unknown" {
		t.Fatal("unchanged file proves execution", unchanged, err)
	}
	wrong, err := FileWrite(before, after, strings.Repeat("a", 64))
	if err != nil || wrong.Result != "unexpected" {
		t.Fatal(wrong, err)
	}
	a.Authorized = false
	e.EvidenceID = "file-denied"
	r, err = s.Submit(e, a, source, time.Now())
	if err != nil || r.FindingCode != "unauthorized_effect_observed" {
		t.Fatal(r, err)
	}
}

func TestFileCaptureBoundsAndUnsafeTargets(t *testing.T) {
	dir := t.TempDir()
	file := filepath.Join(dir, "data")
	if err := os.WriteFile(file, []byte("1234"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := CaptureFile(file, 4); err != nil {
		t.Fatal(err)
	}
	if _, err := CaptureFile(file, 3); err == nil {
		t.Fatal("oversize file accepted")
	}
	for _, p := range []string{dir, "relative", filepath.Join(dir, "missing-parent", "data")} {
		if _, err := CaptureFile(p, 4); err == nil {
			t.Fatal("unsafe target accepted", p)
		}
	}
	link := filepath.Join(dir, "link")
	if err := os.Symlink(file, link); err != nil {
		t.Fatal(err)
	}
	if _, err := CaptureFile(link, 4); err == nil {
		t.Fatal("symlink accepted")
	}
	parent := filepath.Join(dir, "parent-link")
	if err := os.Symlink(dir, parent); err != nil {
		t.Fatal(err)
	}
	if _, err := CaptureFile(filepath.Join(parent, "data"), 4); err == nil {
		t.Fatal("symlink ancestor accepted")
	}
	before, err := CaptureFile(file, 4)
	if err != nil {
		t.Fatal(err)
	}
	bad := before
	bad.CapturedAt = time.Now().Add(-time.Hour).UTC().Format(time.RFC3339Nano)
	if _, err := FileWrite(before, bad, before.Digest); err == nil {
		t.Fatal("reversed observation accepted")
	}
}
