package effectevidence

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"testing"
	"time"
)

func TestEffectStageBaseline(t *testing.T) {
	if os.Getenv("SIQ_STAGE_BASELINE") != "1" {
		t.Skip("explicit performance baseline only")
	}
	_, key, _ := fixture(t)
	s, err := NewStore(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "report")
	before, err := CaptureFile(path, 1024)
	if err != nil {
		t.Fatal(err)
	}
	data := []byte("performance fixture output")
	digest := sha256.Sum256(data)
	if err = os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	after, err := CaptureFile(path, 1024)
	if err != nil {
		t.Fatal(err)
	}
	material, err := FileWrite(before, after, hex.EncodeToString(digest[:]))
	if err != nil {
		t.Fatal(err)
	}
	action := Action{ActionID: "baseline-action", DecisionReceiptID: "baseline-receipt", TaskID: "baseline-task", IssuedAt: time.Now().Add(-time.Minute), Authorized: true, Effects: []string{"file.write"}, Resources: runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "filesystem", Value: path}})}
	source := Source{Type: "host_observer", SourceID: "baseline-host", Independence: "host_independent"}
	samples := []float64{}
	for i := 0; i < 105; i++ {
		start := time.Now()
		record, err := s.SubmitFile(fmt.Sprintf("baseline-%03d", i), material, action, source, time.Now())
		elapsed := time.Since(start)
		if err != nil || record.Evidence.Result != "expected" {
			t.Fatal("effect processing failed", err)
		}
		if i >= 5 {
			samples = append(samples, float64(elapsed)/float64(time.Millisecond))
		}
	}
	raw, err := json.Marshal(map[string][]float64{"effect_evidence_processing": samples})
	if err != nil {
		t.Fatal(err)
	}
	t.Log("SIQ_STAGE_SAMPLES=" + string(raw))
}
