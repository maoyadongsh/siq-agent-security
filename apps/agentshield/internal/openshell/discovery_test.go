package openshell

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const discoveryUUID = "11111111-1111-4111-8111-111111111111"

func TestDiscoverTargetsStrictAndBounded(t *testing.T) {
	row := `{"id":"` + discoveryUUID + `","name":"shared","phase":"Ready","current_policy_version":1,"labels":{"secret":"DO_NOT_COPY"}}`
	for _, raw := range []string{"null", "{}", "[]{}", "[" + row + "," + row + "]", strings.Replace("["+row+"]", "shared", "../escape", 1), strings.Replace("["+row+"]", `"current_policy_version":1`, `"current_policy_version":-1`, 1), "[" + strings.TrimSuffix(strings.Repeat(row+",", 1000), ",") + "]"} {
		if _, err := parseDiscoveredTargets(raw); err == nil {
			t.Fatal("invalid catalog accepted")
		}
	}
	items, err := parseDiscoveredTargets("[" + row + "]")
	if err != nil || len(items) != 1 || items[0].Name != "shared" {
		t.Fatal("valid catalog rejected", err)
	}
	raw, _ := json.Marshal(items)
	if strings.Contains(string(raw), "DO_NOT_COPY") || strings.Contains(string(raw), "labels") {
		t.Fatal("copied private fields")
	}
	items, err = parseDiscoveredTargets(strings.Replace("["+row+"]", "Ready", "unexpected-private-text", 1))
	if err != nil || items[0].Phase != "Unknown" {
		t.Fatal("unknown phase not bounded")
	}
}

func TestDiscoverAndInspectTargetsReadOnly(t *testing.T) {
	vector := loadPolicySafetyVectors(t).ReadCases[0]
	base := vector.Output
	endpoint := "http://127.0.0.1:8080"
	id, badList, drift, reads, forbidden := discoveryUUID, false, false, 0, 0
	c := New(Options{LookupEnv: func(k string) (string, bool) {
		v := map[string]string{envCLIBin: "/fixture/openshell", envEndpoint: endpoint, envInsecure: "1"}[k]
		return v, v != ""
	}, Runner: func(args []string) (int, string, string) {
		switch strings.Join(args, " ") {
		case "gateway info":
			return 0, "Gateway Info\nGateway version: 0.0.104", ""
		case "status":
			return 0, "Server Status\nGateway: fixture", ""
		case "sandbox list --limit 1000 --output json":
			if badList {
				return 1, "", "private error must not escape"
			}
			return 0, `[{"id":"` + id + `","name":"shared","phase":"Ready","current_policy_version":` + vector.Revision + `}]`, ""
		case "policy get shared --full":
			reads++
			if drift {
				id = "22222222-2222-4222-8222-222222222222"
			}
			return 0, base, ""
		default:
			forbidden++
			return 1, "", "unexpected"
		}
	}, DockerRunner: func([]string) (int, string, string) { forbidden++; return 1, "", "forbidden" }})
	cat := c.DiscoverTargets()
	if cat.State != "available" || !cat.CanInspect || len(cat.Items) != 1 || cat.StartedGateway {
		t.Fatalf("invalid catalog %+v", cat)
	}
	result, err := c.InspectDiscoveredTarget(discoveryUUID, "shared", cat.Fingerprint)
	if err != nil || result.State != "policy_readable" || result.Enforcement || reads != 1 || forbidden != 0 {
		t.Fatalf("invalid inspection %+v %v, forbidden %d", result, err, forbidden)
	}
	if os.Getenv("SIQ_UPDATE_ACTIVITY_FIXTURES") == "1" {
		for name, value := range map[string]any{"local-openshell-targets": cat, "local-openshell-target-inspection": result} {
			raw, _ := json.MarshalIndent(value, "", "  ")
			if err := os.WriteFile(filepath.Join("..", "..", "testdata", "contracts", name+".json"), append(raw, '\n'), 0600); err != nil {
				t.Fatal(err)
			}
		}
	}
	if _, err = c.InspectDiscoveredTarget("22222222-2222-4222-8222-222222222222", "shared", cat.Fingerprint); err == nil || reads != 1 {
		t.Fatal("stale UUID reached policy read")
	}
	endpoint = "http://127.0.0.1:8081"
	if _, err = c.InspectDiscoveredTarget(discoveryUUID, "shared", cat.Fingerprint); err == nil || reads != 1 {
		t.Fatal("cross-endpoint selection accepted")
	}
	endpoint = "http://127.0.0.1:8080"
	drift = true
	if _, err = c.InspectDiscoveredTarget(discoveryUUID, "shared", cat.Fingerprint); err == nil {
		t.Fatal("sandbox rebuilt during read accepted")
	}
	badList = true
	if out := c.DiscoverTargets(); out.State != "catalog_unavailable" || len(out.Items) != 0 {
		t.Fatal("list failure became empty success")
	}
	if forbidden != 0 {
		t.Fatal("discovery invoked write or Docker fallback")
	}
}
