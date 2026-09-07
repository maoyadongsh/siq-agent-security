package runtimeaction

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestEnvelopeFixedVector(t *testing.T) {
	e := Envelope{Platform: "hermes", SessionID: "s-1", AgentID: "a-1", TaskID: "task-1", IntentID: "int-test", Tool: "read_file", ToolCallID: "call-1", Operation: "read", Effects: []string{"file.read"}, ParamsDigest: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", OccurredAt: time.Date(2026, 9, 7, 0, 0, 0, 0, time.UTC)}
	e.Principal = &Principal{Type: "user", ID: "u-1"}
	e.ProvenanceRefs = []string{"prov-approved-input"}
	resources, err := ExtractResources(e.Tool, map[string]any{"path": "/work/report"})
	if err != nil {
		t.Fatal(err)
	}
	e.ResourceRefs = ResourceRefs(resources)
	e.ActionID = ActionID(e)
	raw, err := json.MarshalIndent(e, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	raw = append(raw, '\n')
	p := filepath.Join("..", "..", "testdata", "contracts", "runtime-action-envelope.sample.json")
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
		t.Fatal("runtime envelope differs from fixture")
	}
}
