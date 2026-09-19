package inventory

import (
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

type connectorFixture struct {
	Network     bool   `json:"network"`
	WithCollect bool   `json:"with_collect"`
	CandidateID string `json:"candidate_id"`
}

// The fixture is a copy of this self-built Go test executable. Handle --serve
// before testing parses flags; the production exec path and environment stay
// unchanged. Only explicitly installed fixtures have the adjacent config.
func TestMain(m *testing.M) {
	if len(os.Args) == 2 && os.Args[1] == "--serve" && os.Getenv("SIQ_CONNECTOR_NAME") == "hermes" {
		os.Exit(serveConnectorFixture())
	}
	os.Exit(m.Run())
}

func installConnectorFixture(t *testing.T, path string, fixture connectorFixture) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		path += ".exe"
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	src, err := os.Open(executable)
	if err != nil {
		t.Fatal(err)
	}
	defer src.Close()
	dst, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o755)
	if err != nil {
		t.Fatal(err)
	}
	_, copyErr := io.Copy(dst, src)
	closeErr := dst.Close()
	if copyErr != nil {
		t.Fatal(copyErr)
	}
	if closeErr != nil {
		t.Fatal(closeErr)
	}
	if fixture.CandidateID == "" {
		fixture.CandidateID = "connector:extra"
	}
	raw, err := json.Marshal(fixture)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path+".fixture.json", raw, 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func serveConnectorFixture() int {
	executable, err := os.Executable()
	if err != nil {
		return 20
	}
	raw, err := os.ReadFile(executable + ".fixture.json")
	var fixture connectorFixture
	if err != nil || json.Unmarshal(raw, &fixture) != nil || fixture.CandidateID == "" {
		return 21
	}
	if os.Getenv("SIQ_CONNECTOR_VERSION") != "0.1.0" || os.Getenv("SIQ_CONNECTOR_TIMEOUT_MS") != "60000" || os.Getenv("HOME") == "" {
		return 22
	}
	var describe, collect struct {
		ID     string          `json:"id"`
		Op     string          `json:"op"`
		Params json.RawMessage `json:"params"`
	}
	decoder := json.NewDecoder(os.Stdin)
	if decoder.Decode(&describe) != nil || decoder.Decode(&collect) != nil {
		return 23
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF || describe.ID != "1" || describe.Op != "describe" || collect.ID != "2" || collect.Op != "collect" {
		return 24
	}
	var params struct {
		Plan struct {
			Scope struct {
				Roots []string `json:"roots"`
			} `json:"scope"`
			Limits struct {
				MaxFiles int `json:"max_files"`
				MaxBytes int `json:"max_bytes"`
			} `json:"limits"`
		} `json:"plan"`
	}
	if json.Unmarshal(collect.Params, &params) != nil || len(params.Plan.Scope.Roots) != 1 || params.Plan.Scope.Roots[0] != os.Getenv("HOME") || params.Plan.Limits.MaxFiles != 200 || params.Plan.Limits.MaxBytes != 16777216 {
		return 25
	}
	encoder := json.NewEncoder(os.Stdout)
	if encoder.Encode(map[string]any{"id": describe.ID, "ok": true, "result": map[string]any{
		"version": "0.0.1", "objects": []string{"hermes_profile"}, "required_permissions": []string{},
		"data_categories": []string{}, "max_output_bytes": 1024, "network_access": fixture.Network,
	}}) != nil {
		return 26
	}
	if !fixture.WithCollect {
		return 0
	}
	result := map[string]any{
		"candidates": []any{map[string]any{
			"candidate_id": fixture.CandidateID, "source_type": "hermes_profile", "source_locator": "hermes://extra",
			"discovered_at": "2026-09-05T00:00:00Z", "name": "extra", "framework": "hermes",
			"evidence_ids": []string{"ev-conn-1"}, "confidence": 1.0, "status": "candidate",
		}},
		"evidence": []any{map[string]any{
			"evidence_id": "ev-conn-1", "source_type": "platform_config", "source_locator": "hermes://extra",
			"observed_at": "2026-09-05T00:00:00Z", "collected_at": "2026-09-05T00:00:00Z",
			"collector_id": "connector", "connector_version": "0.0.1", "content_hash": strings.Repeat("ab", 32),
			"redaction_profile": "siq.redaction.v1", "classification": "internal", "signature": strings.Repeat("f", 128),
		}},
		"permission_facts": []any{
			map[string]any{"subject": map[string]any{"type": "agent_instance", "id": "extra"}, "domain": "tool", "action": "invoke",
				"resource": map[string]any{"type": "tool", "value": "should-not-appear-effective"}, "effect": "allow",
				"state": "effective", "authority": "connector", "evidence_ids": []string{"ev-conn-1"}},
			map[string]any{"subject": map[string]any{"type": "agent_instance", "id": "extra"}, "domain": "tool", "action": "invoke",
				"resource": map[string]any{"type": "tool", "value": "connector-declared-tool"}, "effect": "allow",
				"state": "declared", "authority": "connector", "evidence_ids": []string{"ev-conn-1"}},
		},
	}
	if encoder.Encode(map[string]any{"id": collect.ID, "ok": true, "result": result}) != nil {
		return 27
	}
	return 0
}
