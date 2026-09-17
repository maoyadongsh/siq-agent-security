package server

import (
	"siq-agent-security/apps/agentshield/internal/openshell"
	"strings"
	"testing"
)

func TestOpenShellRefreshNeverRetainsSuccessCapabilities(t *testing.T) {
	s, _ := newServer(t, "block")
	broken := false
	s.d.Openshell = openshell.New(openshell.Options{EnvScript: "/fixture/env.sh", Runner: func(args []string) (int, string, string) {
		if broken {
			return 1, "", "failure"
		}
		if strings.Join(args, " ") == "status" {
			return 0, "Server Status\nGateway: fixture", ""
		}
		if strings.Join(args, " ") == "gateway info" {
			return 0, "Gateway Info\nGateway version: 0.0.104", ""
		}
		return 1, "", "unexpected"
	}})
	if code, _ := call(t, s, "GET", "/v1/openshell/doctor?target=fixture", "", nil); code != 401 {
		t.Fatal("doctor accepted unauthenticated request")
	}
	code, good := call(t, s, "GET", "/v1/openshell/probe", token, nil)
	if code != 200 || good["ok"] != true || good["configuration_capabilities"] == nil {
		t.Fatal("missing capability facts")
	}
	broken = true
	_, bad := call(t, s, "GET", "/v1/openshell/probe", token, nil)
	if bad["ok"] != false || bad["capabilities"] != nil || bad["handshake_verified"] != nil {
		t.Fatal("failed refresh retained success")
	}
	if s.osCaps != nil {
		t.Fatal("stale cached capability")
	}
	s.d.Openshell = nil
	_, missing := call(t, s, "GET", "/v1/openshell/probe", token, nil)
	if missing["ok"] != false || missing["doctor"].(map[string]any)["state"] != openshell.StateUnconfigured {
		t.Fatal("unconfigured response retained old state")
	}
}
