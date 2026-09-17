package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

// A marker bound to another canonical path (case/Unicode alias on insensitive
// volumes, moved directory) stays fail-closed as "corrupt" but the operator
// hint must name the path spelling problem instead of a broken migration.
func TestStateStatusDistinguishesDirectoryBindingMismatch(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "instance")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	if err := cmdInitialize([]string{"--port", "47619"}, io.Discard); err != nil {
		t.Fatal(err)
	}
	markerPath := filepath.Join(dir, state.StateFormatMarkerName)
	raw, err := os.ReadFile(markerPath)
	if err != nil {
		t.Fatal(err)
	}
	var marker map[string]any
	if err = json.Unmarshal(raw, &marker); err != nil {
		t.Fatal(err)
	}
	original := marker["state_directory_id"].(string)
	marker["state_directory_id"] = strings.Repeat("0", 64)
	rebound, _ := json.Marshal(marker)
	if err = os.WriteFile(markerPath, rebound, 0600); err != nil {
		t.Fatal(err)
	}
	if err = stateformat.Check(dir, true, false); !errors.Is(err, stateformat.ErrBinding) || !errors.Is(err, stateformat.ErrCorrupt) || !errors.Is(err, stateformat.ErrIncompatible) {
		t.Fatal("binding mismatch not classified", err)
	}
	var out bytes.Buffer
	if err = cmdStateStatus(nil, &out); err != nil {
		t.Fatal(err)
	}
	var result struct {
		Compatible bool   `json:"compatible"`
		Status     string `json:"status"`
		Recovery   string `json:"recovery"`
	}
	if err = json.Unmarshal(out.Bytes(), &result); err != nil || result.Compatible || result.Status != state.CompatStatusCorrupt {
		t.Fatalf("binding mismatch must stay fail-closed corrupt: %s %v", out.Bytes(), err)
	}
	if !strings.Contains(result.Recovery, "路径拼写") || strings.Contains(result.Recovery, "state-migrate") {
		t.Fatalf("recovery hint does not name the path spelling problem: %q", result.Recovery)
	}
	if bytes.Contains(out.Bytes(), []byte(dir)) || bytes.Contains(out.Bytes(), []byte(original)) {
		t.Fatal("diagnosis exposed private path or identity")
	}
	// Genuine marker corruption keeps the generic migration hint.
	if err = os.WriteFile(markerPath, []byte(`{"schema":"state-format/v2","x":1}`), 0600); err != nil {
		t.Fatal(err)
	}
	out.Reset()
	if err = cmdStateStatus(nil, &out); err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(out.Bytes(), &result); err != nil || result.Status != state.CompatStatusCorrupt || strings.Contains(result.Recovery, "路径拼写") {
		t.Fatalf("corrupt marker misreported as binding mismatch: %s %v", out.Bytes(), err)
	}
}
