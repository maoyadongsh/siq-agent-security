package server

import (
	"bytes"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
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
	name := "adapter-diagnostics.json"
	if runtime.GOOS == "linux" {
		name = "adapter-diagnostics-linux.json"
	}
	path := filepath.Join("..", "..", "testdata", "contracts", name)
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

func diagnosticStatus(d adapterinstall.Diagnosis, code string) string {
	for _, check := range d.Checks {
		if check.Code == code {
			return check.Status
		}
	}
	return ""
}

func TestDiagnosisSeparatesBackendReachabilityAndHookLoad(t *testing.T) {
	s, _ := newServer(t, "block")
	opts := s.adapterOptions(adapterinstall.Hermes)
	if _, err := adapterinstall.Install(opts); err != nil {
		t.Fatal(err)
	}
	d := s.diagnoseInstance(opts)
	if diagnosticStatus(d, "backend_reachability") != "pass" {
		t.Fatalf("matching endpoint not reported reachable: %+v", d.Checks)
	}
	if diagnosticStatus(d, "hook_load") != "unknown" || diagnosticStatus(d, "host_registration") != "unknown" || diagnosticStatus(d, "platform_compatibility") != "unknown" {
		t.Fatalf("hook load or platform compatibility conflated: %+v", d.Checks)
	}
	config := filepath.Join(s.d.Home, ".hermes", "plugins", "siq-agent-security", "config.json")
	if err := os.WriteFile(config, []byte(`{"endpoint":"http://127.0.0.1:1"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if d := s.diagnoseInstance(opts); diagnosticStatus(d, "backend_reachability") != "fail" {
		t.Fatalf("unreachable backend not diagnosed on its own: %+v", d.Checks)
	}
	openclawOpts := s.adapterOptions(adapterinstall.OpenClaw)
	if _, err := adapterinstall.Install(openclawOpts); err != nil {
		t.Fatal(err)
	}
	if openclaw := s.diagnoseInstance(openclawOpts); diagnosticStatus(openclaw, "hook_load") != "unknown" || diagnosticStatus(openclaw, "backend_reachability") != "pass" {
		t.Fatalf("openclaw hook load or backend not stated honestly: %+v", openclaw.Checks)
	}
}

func TestHookLoadConclusionMapping(t *testing.T) {
	for status, want := range map[string]string{
		"passed": "pass", "failed": "fail", "": "unknown", "invalidated": "unknown",
		"preparing": "unknown", "waiting_host": "unknown", "running": "unknown",
		"cancelled": "unknown", "mystery": "unknown",
	} {
		if got, _ := hookLoadConclusion(status); got != want {
			t.Fatalf("hookLoadConclusion(%q) = %q, want %q", status, got, want)
		}
	}
}

func TestLoopbackProbeNeverLeavesLocalhost(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	_, port, _ := net.SplitHostPort(listener.Addr().String())
	if got := probeLoopback("http://localhost:" + port); got != probeReachable {
		t.Fatal("literal localhost mapping failed", got)
	}
	if got := probeLoopback("http://" + listener.Addr().String()); got != probeReachable {
		t.Fatalf("live listener not reachable: %v", got)
	}
	if got := probeLoopback("http://127.0.0.1:1"); got != probeUnreachable {
		t.Fatalf("closed port not unreachable: %v", got)
	}
	for _, endpoint := range []string{"http://10.0.0.1:47611", "http://localhost.evil.example:47611", "ftp://127.0.0.1:1", "not a url"} {
		if got := probeLoopback(endpoint); got != probeNotLocal {
			t.Fatalf("non-loopback or invalid endpoint probed: %q -> %v", endpoint, got)
		}
	}
}

func TestSameEndpointIgnoresHostCaseOnly(t *testing.T) {
	if !sameEndpoint("http://127.0.0.1:47611", "HTTP://127.0.0.1:47611") {
		t.Fatal("case-equivalent endpoints compared unequal")
	}
	if sameEndpoint("http://127.0.0.1:47611", "https://127.0.0.1:47611") || sameEndpoint("http://127.0.0.1:47611", "http://127.0.0.1:47612") {
		t.Fatal("different endpoints compared equal")
	}
}
