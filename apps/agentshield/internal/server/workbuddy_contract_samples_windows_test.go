package server

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// Explicit test-only export for independent JSON Schema validation. Responses
// contain credential paths, never bearer secrets; no signed content is rewritten.
func workBuddyContractSample(t *testing.T, name string, value any) {
	t.Helper()
	dir := os.Getenv("AGENTSHIELD_WORKBUDDY_CONTRACT_SAMPLES")
	if dir == "" {
		return
	}
	if !filepath.IsAbs(dir) {
		t.Fatal("contract sample directory must be absolute")
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	raw, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, name+".json"), append(raw, '\n'), 0600); err != nil {
		t.Fatal(err)
	}
}
