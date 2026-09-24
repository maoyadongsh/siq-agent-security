package openshell

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

const gatewayRow = `{"name":"registered","endpoint":"https://127.0.0.1:17671","active":true,"auth":"PRIVATE-METADATA"}`

func TestRegisteredGatewayCatalogStrictProjection(t *testing.T) {
	for _, raw := range []string{"null", "{}", "[]{}", "[" + gatewayRow + "," + gatewayRow + "]", strings.Replace("["+gatewayRow+"]", `"name":"registered"`, `"name":"registered","name":"other"`, 1), strings.Replace("["+gatewayRow+"]", `"name":`, `"Name":`, 1), strings.Replace("["+gatewayRow+"]", "registered", "../escape", 1), strings.Replace("["+gatewayRow+"]", "https://127.0.0.1:17671", "http://remote.example", 1), strings.Replace("["+gatewayRow+"]", "https://127.0.0.1:17671", "https://user:secret@remote.example", 1), strings.Replace("["+gatewayRow+"]", `"active":true`, `"active":null`, 1), strings.Repeat(" ", 1<<20) + "[]"} {
		if _, err := parseRegisteredGateways(raw, "fixture"); err == nil {
			t.Fatal("invalid catalog accepted")
		}
	}
	items, err := parseRegisteredGateways("["+gatewayRow+"]", "fixture")
	if err != nil || len(items) != 1 || !items[0].Active {
		t.Fatal("valid catalog rejected")
	}
	raw, _ := json.Marshal(items)
	if strings.Contains(string(raw), "PRIVATE") || strings.Contains(string(raw), "auth") {
		t.Fatal("private metadata escaped")
	}
	changed, _ := parseRegisteredGateways(strings.Replace("["+gatewayRow+"]", "17671", "17771", 1), "fixture")
	if changed[0].ID != items[0].ID || changed[0].Fingerprint == items[0].Fingerprint {
		t.Fatal("registration change not bound")
	}
	other, _ := parseRegisteredGateways("["+gatewayRow+"]", "other-cli")
	if other[0].ID == items[0].ID {
		t.Fatal("CLI context not bound")
	}
	rows := make([]map[string]any, 128)
	for i := range rows {
		rows[i] = map[string]any{"name": strings.Repeat("a", 1) + string(rune('a'+i/26)) + string(rune('a'+i%26)), "endpoint": "https://127.0.0.1:17671", "active": false}
	}
	raw, _ = json.Marshal(rows)
	if _, err := parseRegisteredGateways(string(raw), "fixture"); err != nil {
		t.Fatal("128 registrations rejected")
	}
	rows = append(rows, map[string]any{"name": "extra", "endpoint": "https://127.0.0.1:17671", "active": false})
	raw, _ = json.Marshal(rows)
	if _, err := parseRegisteredGateways(string(raw), "fixture"); err == nil {
		t.Fatal("over-limit registrations accepted")
	}
}

func TestRegisteredGatewaySelectionNeverChangesRuntimeClient(t *testing.T) {
	cli := filepath.Join(t.TempDir(), "openshell")
	if err := os.WriteFile(cli, []byte("fixture CLI identity"), 0700); err != nil {
		t.Fatal(err)
	}
	metadata := "[" + gatewayRow + "]"
	calls := 0
	env := map[string]string{envCLIBin: cli, envEndpoint: "http://127.0.0.1:8080", envInsecure: "1", "HOME": "/fixture/home", "XDG_CONFIG_HOME": "/fixture/xdg"}
	c := New(Options{LookupEnv: func(k string) (string, bool) { v, ok := env[k]; return v, ok }, Runner: func(args []string) (int, string, string) {
		calls++
		if !reflect.DeepEqual(args, []string{"gateway", "list", "--output", "json"}) {
			t.Error("discovery invoked non-list command")
		}
		return 0, metadata, ""
	}})
	before, err := c.BuildCommand([]string{"status"})
	if err != nil {
		t.Fatal(err)
	}
	cat := c.DiscoverGateways()
	if cat.State != "available" || len(cat.Items) != 1 || cat.Started || cat.ChangedSelection || calls != 1 {
		t.Fatal("invalid gateway discovery")
	}
	row := cat.Items[0]
	child, selected, err := c.selectedGateway(row.ID, row.Fingerprint)
	if err != nil || selected.Name != row.Name {
		t.Fatal("selection failed")
	}
	cmd, err := child.BuildCommand([]string{"status"})
	if err != nil || !reflect.DeepEqual(cmd, []string{cli, "--gateway-endpoint", "https://127.0.0.1:17671", "--gateway", "registered", "status"}) {
		t.Fatal("selection did not pin endpoint and TLS")
	}
	after, _ := c.BuildCommand([]string{"status"})
	if !reflect.DeepEqual(before, after) {
		t.Fatal("changed runtime client")
	}
	{
		vector := loadPolicySafetyVectors(t).ReadCases[0]
		child.Runner = func(args []string) (int, string, string) {
			switch strings.Join(args, " ") {
			case "gateway info":
				return 0, "Gateway Info\nGateway version: 0.0.104", ""
			case "status":
				return 0, "Server Status\nGateway: registered", ""
			case "sandbox list --limit 1000 --output json":
				return 0, `[{"id":"` + discoveryUUID + `","name":"shared","phase":"Ready","current_policy_version":` + vector.Revision + `}]`, ""
			case "policy get shared --full":
				return 0, vector.Output, ""
			default:
				t.Error("unexpected command")
				return 1, "", "unexpected"
			}
		}
		targets := child.DiscoverTargets()
		if _, err := child.inspectDiscoveredTarget(discoveryUUID, "shared", targets.Fingerprint, "different-gateway"); err == nil {
			t.Fatal("wrong native gateway identity accepted")
		}
		inspection, err := child.InspectDiscoveredTarget(discoveryUUID, "shared", targets.Fingerprint)
		if err != nil {
			t.Fatal(err)
		}
		selection := map[string]any{"schema_version": "local-openshell-gateway-select/v1", "gateway_id": row.ID, "configuration_fingerprint": row.Fingerprint}
		inspect := map[string]any{"schema_version": "local-openshell-gateway-inspect/v1", "gateway_id": row.ID, "configuration_fingerprint": row.Fingerprint, "sandbox_id": discoveryUUID, "name": "shared", "endpoint_fingerprint": targets.Fingerprint}
		for name, v := range map[string]any{"local-openshell-gateways": cat, "local-openshell-gateway-select": selection,
			"local-openshell-gateway-targets":    GatewayTargets{Schema: "local-openshell-gateway-targets/v1", ID: row.ID, Fingerprint: row.Fingerprint, Catalog: targets},
			"local-openshell-gateway-inspect":    inspect,
			"local-openshell-gateway-inspection": GatewayInspection{Schema: "local-openshell-gateway-inspection/v1", ID: row.ID, Fingerprint: row.Fingerprint, Inspection: inspection}} {
			if os.Getenv("SIQ_UPDATE_GATEWAY_FIXTURES") != "1" {
				continue
			}
			raw, _ := json.MarshalIndent(v, "", "  ")
			if err := os.WriteFile(filepath.Join("..", "..", "testdata", "contracts", name+".json"), append(raw, '\n'), 0600); err != nil {
				t.Fatal(err)
			}
		}
	}
	metadata = strings.Replace(metadata, "17671", "17771", 1)
	if _, _, err := c.selectedGateway(row.ID, row.Fingerprint); err == nil {
		t.Fatal("stale endpoint accepted")
	}
	metadata = "[]"
	if _, _, err := c.selectedGateway(row.ID, row.Fingerprint); err == nil {
		t.Fatal("removed registration accepted")
	}
	metadata = "invalid PRIVATE"
	if cat := c.DiscoverGateways(); cat.State != "unavailable" || len(cat.Items) != 0 {
		t.Fatal("invalid list became empty success")
	}
	delete(env, envEndpoint)
	if cat := c.DiscoverGateways(); cat.State != "unsupported" {
		t.Fatal("partial config accepted")
	}
}
