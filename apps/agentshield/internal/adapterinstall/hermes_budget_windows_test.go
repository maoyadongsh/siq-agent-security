//go:build windows

package adapterinstall

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestHermesWindowsInstalledRequestBudget(t *testing.T) {
	o := testOpts(t, Hermes)
	if _, err := Install(o); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join(o.Home, ".hermes", "plugins", "siq-agent-security", "config.json"))
	if err != nil {
		t.Fatal(err)
	}
	var cfg map[string]any
	if err := json.Unmarshal(raw, &cfg); err != nil {
		t.Fatal(err)
	}
	if cfg["timeout_s"] != float64(20) || cfg["enforcement_mode"] != "block" {
		t.Fatalf("installation must preserve blocking mode and wait for bounded validation: %v", cfg)
	}
	if _, err := Uninstall(o); err != nil {
		t.Fatal(err)
	}
}
