package server

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func instanceFixture(t *testing.T, s *Server) []any {
	t.Helper()
	path := filepath.Join(s.d.Home, ".hermes", "profiles", "work")
	if err := os.MkdirAll(path, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(path, "config.yaml"), []byte("model: fixture\n"), 0600); err != nil {
		t.Fatal(err)
	}
	code, result := call(t, s, "GET", "/v1/adapter/instances?platform=hermes", token, nil)
	if code != 200 {
		t.Fatal(result)
	}
	return result["instances"].([]any)
}
func TestInstanceManagementRequiresAdminAndPreventsTargetSwitch(t *testing.T) {
	s, _ := newServer(t, "block")
	s.d.HermesOS = "linux"
	s.d.HermesCLI = filepath.Join(s.d.Home, "missing-cli")
	res := sessionRequest(t, s, "GET", "/v1/adapter/instances?platform=hermes", nil, token, nil, nil)
	if res.Code != 403 {
		t.Fatal("decision credential listed instances")
	}
	rows := instanceFixture(t, s)
	if len(rows) != 2 {
		t.Fatal("profile not listed")
	}
	first := rows[0].(map[string]any)["instance_id"]
	second := rows[1].(map[string]any)["instance_id"]
	code, view := call(t, s, "POST", "/v1/adapter/preview", token, map[string]any{"platform": "hermes", "action": "install", "instance_id": second})
	if code != 200 || view["schema_version"] != "local-adapter-plan/v2" || view["instance_id"] != second {
		t.Fatalf("instance preview: %d %v", code, view)
	}
	body := map[string]any{"platform": "hermes", "plan_id": view["plan_id"], "plan_digest": view["plan_digest"], "instance_id": first}
	if code, _ := call(t, s, "POST", "/v1/adapter/install", token, body); code != 409 {
		t.Fatal("target switched after preview")
	}
	body["instance_id"] = second
	if code, res := call(t, s, "POST", "/v1/adapter/install", token, body); code != 200 {
		t.Fatal(res)
	}
	if _, err := os.Stat(filepath.Join(s.d.Home, ".hermes", "plugins")); !os.IsNotExist(err) {
		t.Fatal("default profile touched")
	}
	if _, err := os.Stat(filepath.Join(s.d.Home, ".hermes", "profiles", "work", "plugins", "siq-agent-security", "plugin.yaml")); err != nil {
		t.Fatal("selected profile not installed")
	}
}
func TestInstanceAndPlanV2ContractFixtures(t *testing.T) {
	s, _ := newServer(t, "block")
	s.d.HermesOS = "linux"
	s.d.HermesCLI = filepath.Join(s.d.Home, "missing-cli")
	_ = instanceFixture(t, s)
	_, view := call(t, s, "GET", "/v1/adapter/instances?platform=hermes", token, nil)
	rows := view["instances"].([]any)
	selected := rows[1].(map[string]any)["instance_id"]
	code, plan := call(t, s, "POST", "/v1/adapter/preview", token, map[string]any{"platform": "hermes", "action": "install", "instance_id": selected})
	if code != 200 {
		t.Fatal(plan)
	}
	for i, row := range rows {
		row.(map[string]any)["instance_id"] = fmt.Sprintf("hi-%032x", i+1)
	}
	plan["plan_id"] = "ap-00000000000000000000000000000000"
	plan["plan_digest"] = fmt.Sprintf("%064x", 0)
	plan["instance_id"] = fmt.Sprintf("hi-%032x", 2)
	plan["expires_at"] = "2026-09-10T09:00:00Z"
	// Program and state paths affect generated files; contract fixtures use digest tokens, not host-dependent values.
	for _, change := range plan["changes"].([]any) {
		row := change.(map[string]any)
		if row["before_sha256"] != "" {
			row["before_sha256"] = fmt.Sprintf("%064x", 0)
		}
		if row["after_sha256"] != "" {
			row["after_sha256"] = fmt.Sprintf("%064x", 0)
		}
	}
	for name, value := range map[string]any{"adapter-instances.json": view, "adapter-plan.v2.json": plan} {
		raw, _ := json.MarshalIndent(value, "", "  ")
		raw = append(raw, '\n')
		path := filepath.Join("..", "..", "testdata", "contracts", name)
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(path, raw, 0644); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil || string(expected) != string(raw) {
			t.Fatalf("contract drift: %s", name)
		}
	}
}
