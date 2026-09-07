package perfbaseline

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/signing"
	"time"
)

// MeasureIntent measures local signature/digest lookup plus deterministic matching.
// It deliberately does not claim full daemon, adapter or filesystem execution latency.
func MeasureIntent() ([]byte, error) { return MeasureIntentScale(1, 200) }

func MeasureIntentScale(bindings, samples int) ([]byte, error) {
	if bindings < 1 || bindings > 4096 || samples < 1 || samples > 10000 {
		return nil, fmt.Errorf("intent benchmark: bindings must be 1..4096 and samples 1..10000")
	}
	dir, err := os.MkdirTemp("", "siq-intent-perf-")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(dir)
	key, _ := signing.FromSeed(bytes.Repeat([]byte{19}, 32))
	store, err := intent.Open(dir, key)
	if err != nil {
		return nil, err
	}
	now := time.Now().UTC()
	c := intent.Contract{SchemaVersion: "intent/v2", IntentID: "int-perf", TaskID: "task-perf", Principal: intent.Principal{Type: "user", ID: "perf"}, Agent: intent.Agent{ID: "perf", Platform: "hermes"}, Purpose: "local benchmark", AllowedTools: []string{"read_file"}, AllowedEffects: []string{"file.read"}, ResourceConstraints: []intent.ResourceConstraint{{Domain: "filesystem", Operator: "prefix", Value: "/company-a/"}}, ParameterConstraints: []intent.ParameterConstraint{}, IssuedAt: now.Add(-time.Minute).Format(time.RFC3339), ValidFrom: now.Add(-time.Minute).Format(time.RFC3339), ExpiresAt: now.Add(time.Hour).Format(time.RFC3339), Authority: intent.Authority{Issuer: "benchmark", Revision: "1", EvidenceIDs: []string{}}}
	if _, err = store.Issue(c); err != nil {
		return nil, err
	}
	for i := 0; i < bindings; i++ {
		if _, err = store.Bind(intent.Binding{Platform: "hermes", SessionID: fmt.Sprintf("perf-%d", i), AgentID: "perf", IntentID: c.IntentID}); err != nil {
			return nil, err
		}
	}
	lookup := make([]float64, samples)
	missing := make([]float64, samples)
	match := make([]float64, samples)
	for i := range lookup {
		start := time.Now()
		resolved, _, err := store.ResolveBinding("hermes", fmt.Sprintf("perf-%d", i%bindings), "perf")
		if err != nil {
			return nil, err
		}
		lookup[i] = float64(time.Since(start)) / float64(time.Millisecond)
		if resolved == nil {
			return nil, fmt.Errorf("intent benchmark: expected binding missing")
		}
		start = time.Now()
		absent, _, err := store.ResolveBinding("hermes", "absent-session", "perf")
		if err != nil {
			return nil, err
		}
		if absent != nil {
			return nil, fmt.Errorf("intent benchmark: unexpected missing lookup authority")
		}
		missing[i] = float64(time.Since(start)) / float64(time.Millisecond)
		start = time.Now()
		err = resolved.Authorize("hermes", "perf", "", "read_file", map[string]any{"path": "/company-a/report.txt"}, time.Now())
		if err != nil {
			return nil, err
		}
		match[i] = float64(time.Since(start)) / float64(time.Millisecond)
	}
	return json.MarshalIndent(map[string]any{"format": "intent.perf_baseline.v1", "measured_at": time.Now().UTC().Format(time.RFC3339), "go_version": runtime.Version(), "os": runtime.GOOS, "arch": runtime.GOARCH, "bindings": bindings, "samples": len(lookup), "lookup_ms": percentiles(lookup), "matcher_ms": percentiles(match), "missing_lookup_ms": percentiles(missing), "notes": HonestyNote + " Excludes fixture setup, HTTP, receipt fsync and actual effects."}, "", "  ")
}
