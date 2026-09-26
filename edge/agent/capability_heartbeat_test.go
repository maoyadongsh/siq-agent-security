package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHeartbeatCapabilityWire(t *testing.T) {
	for _, clear := range []bool{false, true} {
		t.Run(map[bool]string{false: "legacy", true: "empty_inventory"}[clear], func(t *testing.T) {
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				var body map[string]json.RawMessage
				if json.NewDecoder(r.Body).Decode(&body) != nil {
					t.Error("invalid heartbeat")
				}
				_, present := body["capabilities"]
				if present != clear {
					t.Error("legacy and empty semantics confused")
				}
				if clear {
					var caps struct {
						Connectors []string `json:"connectors"`
					}
					if json.Unmarshal(body["capabilities"], &caps) != nil || caps.Connectors == nil || len(caps.Connectors) != 0 {
						t.Error("empty inventory not encoded")
					}
				}
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte(`{"ok":true}`))
			}))
			defer server.Close()
			client := NewClient(ClientConfig{ControlPlaneURL: server.URL})
			var caps map[string]any
			if clear {
				caps = map[string]any{"inventory_schema": "enterprise-installed-capabilities/v1", "protocol_version": "connector-protocol.v1", "connectors": []string{}, "connector_versions": map[string]string{}, "data_categories": []string{}}
			}
			if err := client.HeartbeatWithCapabilities(context.Background(), caps); err != nil {
				t.Fatal(err)
			}
			if calls != 1 {
				t.Fatal("unexpected retry")
			}
		})
	}
}
