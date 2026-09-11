package server

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestAdapterDiagnosticContractAndAuthority(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, method := range []string{"GET", "POST"} {
		if got := sessionRequest(t, s, method, "/v1/adapter/diagnostics", nil, token, nil, nil); got.Code != 403 {
			t.Fatal("decision credential reached management diagnosis")
		}
	}
	response := sessionRequest(t, s, "GET", "/v1/adapter/diagnostics", nil, s.bootAdmin, nil, nil)
	if response.Code != 200 || response.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("diagnosis failed or cacheable")
	}
	var body any
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	got, _ := json.MarshalIndent(body, "", "  ")
	path := filepath.Join("..", "..", "testdata", "contracts", "adapter-diagnostics.json")
	if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
		if err := os.WriteFile(path, append(got, '\n'), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	expected, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(bytes.TrimSpace(expected), got) {
		t.Fatal("adapter diagnosis contract changed")
	}
}
