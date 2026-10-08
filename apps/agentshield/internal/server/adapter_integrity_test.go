package server

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
)

func TestAdapterDiagnosticsReportsMissingInstalledHook(t *testing.T) {
	s, _ := newServer(t, "block")
	opts := s.adapterOptions(adapterinstall.Hermes)
	if _, err := adapterinstall.Install(opts); err != nil {
		t.Fatal(err)
	}
	plugin := filepath.Join(opts.Home, ".hermes", "plugins", "siq-agent-security")
	if err := os.RemoveAll(plugin); err != nil {
		t.Fatal(err)
	}
	response := sessionRequest(t, s, "GET", "/v1/adapter/diagnostics", nil, s.bootAdmin, nil, nil)
	if response.Code != 200 || response.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("diagnosis response unavailable")
	}
	var body struct {
		Platforms []adapterinstall.Diagnosis `json:"platforms"`
	}
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	for _, d := range body.Platforms {
		if d.Platform == adapterinstall.Hermes {
			if d.ConfigurationState != "incomplete" || d.RuntimeState != "unverified" || diagnosticStatus(d, "adapter_files") != "fail" {
				t.Fatalf("lost hook hidden at HTTP boundary: %+v", d)
			}
			if bytes.Contains(response.Body.Bytes(), []byte(opts.StateDir)) || bytes.Contains(response.Body.Bytes(), []byte(plugin)) {
				t.Fatal("diagnosis exposed private paths")
			}
			if _, err := os.Stat(plugin); !os.IsNotExist(err) {
				t.Fatal("diagnosis recreated removed hooks")
			}
			return
		}
	}
	t.Fatal("missing Hermes diagnosis")
}
