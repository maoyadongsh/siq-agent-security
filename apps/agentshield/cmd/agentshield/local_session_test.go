package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/state"
)

const healthResponse = `{"schema_version":"local-service-instance-health/v1","product":"siq-agent-security","version":"test","local_mode":true,"status":"ready","state_directory_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}`

func TestLocalInstanceRejectsWrongDirectoryBeforePairing(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	id, err := (&state.Store{Dir: dir}).DirectoryID()
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name, identity, schema string
		accepted               bool
	}{
		{"matching", id, "local-service-instance-health/v1", true},
		{"other directory", strings.Repeat("0", 64), "local-service-instance-health/v1", false},
		{"missing identity", "", "local-service-instance-health/v1", false},
		{"legacy service", id, "local-service-health/v1", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("Authorization") != "" || r.URL.Path != "/healthz/instance" {
					t.Error("instance check sent credentials or attempted pairing")
				}
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(localHealth{SchemaVersion: tc.schema, Product: "siq-agent-security", Version: "test", LocalMode: true, Status: "ready", StateDirectoryID: tc.identity})
			}))
			defer srv.Close()
			client := localClient()
			defer client.CloseIdleConnections()
			_, err := probeLocalInstance(client, srv.URL, &state.Store{Dir: dir})
			if (err == nil) != tc.accepted {
				t.Fatalf("unexpected result: %v", err)
			}
			if !tc.accepted {
				port := strings.TrimPrefix(srv.URL, "http://127.0.0.1:")
				if err := cmdLocalSession("pair", []string{"--port", port}); err == nil {
					t.Fatal("mismatched instance allowed pairing")
				}
			}
		})
	}
}

func TestLocalServiceIdentity(t *testing.T) {
	st := &state.Store{Dir: t.TempDir()}
	id, err := st.DirectoryID()
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name, body, contentType string
		accepted                bool
	}{
		{"ready", healthResponse, "application/json", true},
		{"SPA fallback", "<html>another app</html>", "text/html", false},
		{"wrong media type", healthResponse, "application/jsonp", false},
		{"wrong product", strings.ReplaceAll(healthResponse, "siq-agent-security", "another-app"), "application/json", false},
		{"not ready", strings.ReplaceAll(healthResponse, "ready", "starting"), "application/json", false},
		{"wrong schema", strings.ReplaceAll(healthResponse, "/v1", "/v99"), "application/json", false},
		{"oversized", strings.Repeat(" ", 8193) + healthResponse, "application/json", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("Authorization") != "" {
					t.Error("health received credential")
				}
				w.Header().Set("Content-Type", tc.contentType)
				_, _ = w.Write([]byte(strings.ReplaceAll(tc.body, strings.Repeat("a", 64), id)))
			}))
			defer srv.Close()
			client := localClient()
			defer client.CloseIdleConnections()
			_, err := probeLocalInstance(client, srv.URL, st)
			if (err == nil) != tc.accepted {
				t.Fatal("unexpected identity result")
			}
		})
	}
}

func TestLocalPairingNeverFollowsRedirect(t *testing.T) {
	for _, code := range []int{301, 302, 307, 308} {
		called := false
		target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { called = true }))
		source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, target.URL, code) }))
		client := localClient()
		if _, err := requestLocalPairing(client, source.URL, strings.Repeat("a", 64)); err == nil {
			t.Error("redirect accepted")
		}
		client.CloseIdleConnections()
		source.Close()
		target.Close()
		if called {
			t.Fatal("credential request followed redirect")
		}
	}
}

func TestLocalPairingProtocol(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" || r.Header.Get("X-SIQ-Local-CLI") != "1" || r.Header.Get("Authorization") != "Bearer "+strings.Repeat("a", 64) {
			t.Error("invalid CLI request")
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"schema_version":"local-pairing/v1","code":"aaaa-bbbb-cccc-dddd","expires_in":300}`))
	}))
	defer srv.Close()
	client := localClient()
	defer client.CloseIdleConnections()
	if _, err := requestLocalPairing(client, srv.URL, strings.Repeat("a", 64)); err != nil {
		t.Fatal(err)
	}
	if client.Transport.(*http.Transport).Proxy != nil {
		t.Fatal("local credentials must not use a proxy")
	}
}

func TestLocalStatusDoesNotCreateState(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "uninstalled")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	// Validation fails before networking; even failure must leave no state behind.
	if err := cmdLocalSession("status", []string{"--port", "70000"}); err == nil {
		t.Fatal("invalid port accepted")
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("status created a state directory")
	}
}
