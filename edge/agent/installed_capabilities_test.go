package main

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"

	"siq-agent-security/edge/agent/installplan"
	"siq-agent-security/edge/agent/protocol"
)

func TestRegistrationUsesMeasuredCapabilities(t *testing.T) {
	t.Setenv("SIQ_EDGE_STATE_DIR", filepath.Join(t.TempDir(), "private"))
	caps, err := installedCapabilities(context.Background(), t.TempDir(), capabilityFixture(), func(context.Context, string, installplan.Connector) (*protocol.ConnectorCapabilities, *protocol.ValidationResult, error) {
		return describedFixture(), &protocol.ValidationResult{Valid: true}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		var body RegisterRequest
		if json.NewDecoder(r.Body).Decode(&body) != nil {
			t.Error("invalid registration")
		}
		encoded, _ := json.Marshal(body.Capabilities)
		expected, _ := json.Marshal(caps)
		if string(encoded) != string(expected) || body.ExpectedEnvironmentID != "env-1" {
			t.Error("measured capability projection lost")
		}
		_ = json.NewEncoder(w).Encode(RegisterResponse{EnvironmentID: "env-1", EdgeAgentID: "fixture", DeviceSecret: "synthetic", ControlPlanePublicKey: base64.StdEncoding.EncodeToString(make([]byte, 32))})
	}))
	defer server.Close()
	if err := registerWithCapabilities(context.Background(), []string{"--control-plane", server.URL, "--environment", "env-1", "--enrollment-code", "synthetic"}, caps); err != nil {
		t.Fatal(err)
	}
	if calls != 1 {
		t.Fatal("unexpected registration calls")
	}
}

func capabilityFixture() *installplan.Plan {
	return &installplan.Plan{TargetArch: "arm64", Connectors: []installplan.Connector{{ID: "hermes", Version: "0.1.0", ProtocolVersion: "connector-protocol.v1", Scope: installplan.Scope{Roots: []string{"~/.hermes/profiles/*"}, Include: []string{"SOUL.md"}}}}}
}
func describedFixture() *protocol.ConnectorCapabilities {
	return &protocol.ConnectorCapabilities{Version: "0.1.0", Objects: []string{"hermes_profile"}, DataCategories: []string{"tool_names", "config_names"}, RequiredPermissions: []string{"read:/home/测试 user/.hermes"}, MaxOutputBytes: 8 << 20}
}
func TestInstalledCapabilities(t *testing.T) {
	stage := t.TempDir()
	calls := 0
	caps, err := installedCapabilities(context.Background(), stage, capabilityFixture(), func(ctx context.Context, path string, c installplan.Connector) (*protocol.ConnectorCapabilities, *protocol.ValidationResult, error) {
		calls++
		if path != filepath.Join(stage, "bin", "arm64", "hermes-connector") || c.ID != "hermes" {
			t.Fatal("unselected executable")
		}
		deadline, ok := ctx.Deadline()
		if !ok || time.Until(deadline) > 5*time.Second {
			t.Fatal("unbounded probe")
		}
		return describedFixture(), &protocol.ValidationResult{Valid: true}, nil
	})
	if err != nil || calls != 1 {
		t.Fatalf("probe %d: %v", calls, err)
	}
	if !reflect.DeepEqual(caps["connectors"], []string{"hermes"}) || !reflect.DeepEqual(caps["connector_versions"], map[string]string{"hermes": "0.1.0"}) {
		t.Fatal(caps)
	}
	if strings.Contains(strings.TrimSpace(strings.Join(caps["data_categories"].([]string), ",")), "home") {
		t.Fatal("private path reported")
	}
}
func TestInstalledCapabilitiesRejects(t *testing.T) {
	for _, name := range []string{"missing", "version", "scope", "scope_errors", "output", "object", "category", "permission", "nil"} {
		t.Run(name, func(t *testing.T) {
			caps, err := installedCapabilities(context.Background(), t.TempDir(), capabilityFixture(), func(context.Context, string, installplan.Connector) (*protocol.ConnectorCapabilities, *protocol.ValidationResult, error) {
				c := describedFixture()
				s := &protocol.ValidationResult{Valid: true}
				switch name {
				case "missing":
					return nil, nil, errors.New("private diagnostic should not escape")
				case "version":
					c.Version = "2.0.0"
				case "scope":
					s.Valid = false
				case "scope_errors":
					s.Errors = []string{"private path"}
				case "output":
					c.MaxOutputBytes = 9 << 20
				case "object":
					c.Objects = nil
				case "category":
					c.DataCategories = []string{"secret\nvalue"}
				case "permission":
					c.RequiredPermissions = []string{"private\npath"}
				case "nil":
					return nil, nil, nil
				}
				return c, s, nil
			})
			if caps != nil || err != errInstalledCapabilities {
				t.Fatalf("accepted %v %v", caps, err)
			}
		})
	}
}
func TestInstalledCapabilitiesCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := installedCapabilities(ctx, t.TempDir(), capabilityFixture(), func(context.Context, string, installplan.Connector) (*protocol.ConnectorCapabilities, *protocol.ValidationResult, error) {
		t.Fatal("probe after cancellation")
		return nil, nil, nil
	})
	if !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
}

func TestInstalledSkillTaskCapabilities(t *testing.T) {
	for _, scenario := range []string{"supported", "network", "old_directory", "other_connector"} {
		t.Run(scenario, func(t *testing.T) {
			plan := capabilityFixture()
			plan.Connectors[0].ID = "directory"
			if scenario == "other_connector" {
				plan.Connectors[0].ID = "hermes"
			}
			value, err := installedCapabilities(context.Background(), t.TempDir(), plan, func(context.Context, string, installplan.Connector) (*protocol.ConnectorCapabilities, *protocol.ValidationResult, error) {
				caps := describedFixture()
				caps.Objects = []string{"skill_manifest"}
				caps.NetworkAccess = scenario == "network"
				if scenario == "old_directory" {
					caps.Objects = []string{"agent_manifest"}
				}
				return caps, &protocol.ValidationResult{Valid: true}, nil
			})
			if err != nil || value["inventory_schema"] != "enterprise-installed-capabilities/v2" {
				t.Fatal("versioned capability missing", err)
			}
			want := []string{"scan"}
			if scenario == "supported" {
				want = append(want, "skill_scan")
			}
			if !reflect.DeepEqual(value["connector_task_types"].(map[string][]string)[plan.Connectors[0].ID], want) {
				t.Fatal("unsupported skill task advertised", value)
			}
		})
	}
}
func TestInstalledCapabilitiesSubprocess(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX fixture")
	}
	path := filepath.Join(t.TempDir(), "connector")
	// Only describe and validate_scope are accepted. Any additional call exits.
	script := `#!/bin/sh
read -r request
case "$request" in *'"op":"describe"'*) ;; *) exit 2;; esac
printf '%s\n' '{"id":"req-000001","ok":true,"result":{"version":"0.1.0","objects":["hermes_profile"],"data_categories":["config_names"],"max_output_bytes":8388608}}'
read -r request
case "$request" in *'"op":"validate_scope"'*) ;; *) exit 3;; esac
printf '%s\n' '{"id":"req-000002","ok":true,"result":{"valid":true,"errors":[]}}'
exit 0
`
	if err := os.WriteFile(path, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	c, s, err := probeInstalledConnector(context.Background(), path, capabilityFixture().Connectors[0])
	if err != nil || c.Version != "0.1.0" || !s.Valid {
		t.Fatalf("probe failed: %v", err)
	}
	_, _, err = probeInstalledConnector(context.Background(), path+"missing", capabilityFixture().Connectors[0])
	if err != errInstalledCapabilities {
		t.Fatal(err)
	}
}
