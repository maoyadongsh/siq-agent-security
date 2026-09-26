package installplan

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

func fixture(t *testing.T) []byte {
	t.Helper()
	raw, err := os.ReadFile("testdata/plan.json")
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func TestPlanRoundTripAndBinding(t *testing.T) {
	p, err := Parse(fixture(t))
	if err != nil {
		t.Fatal(err)
	}
	now, _ := time.Parse(time.RFC3339, "2026-09-25T01:00:00Z")
	if err := p.RequireCurrent(now, p.TenantID, p.EnvironmentID, p.ControlPlaneOrigin, p.TargetArch); err != nil {
		t.Fatal(err)
	}
	for i, context := range [][]string{
		{"other", p.EnvironmentID, p.ControlPlaneOrigin, p.TargetArch},
		{p.TenantID, "other", p.ControlPlaneOrigin, p.TargetArch},
		{p.TenantID, p.EnvironmentID, "https://attacker.test", p.TargetArch},
		{p.TenantID, p.EnvironmentID, p.ControlPlaneOrigin, "amd64"},
	} {
		if p.RequireCurrent(now, context[0], context[1], context[2], context[3]) == nil {
			t.Fatalf("context %d accepted", i)
		}
	}
	for _, invalid := range []time.Time{now.Add(-time.Nanosecond), now.Add(15 * time.Minute)} {
		if p.RequireCurrent(invalid, p.TenantID, p.EnvironmentID, p.ControlPlaneOrigin, p.TargetArch) == nil {
			t.Fatal("invalid time accepted")
		}
	}
	wire, _ := json.Marshal(p)
	if _, err := Parse(wire); err != nil {
		t.Fatal(err)
	}
}

func TestRejectAmbiguousJSON(t *testing.T) {
	raw := string(fixture(t))
	for _, input := range []string{
		raw + `{}`, strings.Replace(raw, `"purpose":`, `"Purpose":`, 1),
		strings.Replace(raw, `"purpose":`, `"purpose":"enforce","purpose":`, 1),
		strings.Replace(raw, `"target_os": "linux"`, `"target_os": null`, 1),
		strings.Replace(raw, `"purpose":`, `"secret":"sensitive-value","purpose":`, 1),
		strings.Repeat(" ", MaxBytes+1), `{`, `[]`, `null`,
	} {
		if _, err := Parse([]byte(input)); err != ErrInvalid {
			t.Fatalf("invalid input accepted or unsafe error: %v", err)
		}
	}
}

func TestRejectInvalidFields(t *testing.T) {
	for _, pair := range [][2]string{
		{"control_plane_origin", "http://192.168.2.121:10082"},
		{"control_plane_origin", "https://a.test:65536"},
		{"control_plane_origin", "https://a.test?"},
		{"control_plane_origin", "https://a.test#"},
		{"control_plane_origin", "https://user:secret@a.test"},
		{"expires_at", "2026-09-25T01:15:01Z"}, {"issued_at", "0000-01-01T00:00:00Z"},
		{"purpose", "enforce"}, {"tenant_id", ""}, {"target_arch", "x86"},
	} {
		var m map[string]any
		_ = json.Unmarshal(fixture(t), &m)
		m[pair[0]] = pair[1]
		raw, _ := json.Marshal(m)
		if _, err := Parse(raw); err == nil {
			t.Fatalf("accepted %s", pair[0])
		}
	}
}

// Used by the Python contract suite with private temporary files. It validates
// actual Go parsing and writes only accepted, synthetic round-tripped documents.
func TestInstallPlanWireParity(t *testing.T) {
	path := os.Getenv("SIQ_INSTALL_PLAN_TEST_CORPUS")
	if path == "" {
		t.Skip("Python contract suite supplies shared corpus")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Plan  json.RawMessage `json:"plan"`
		Valid bool            `json:"valid"`
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	accepted := []*Plan{}
	for i, c := range cases {
		p, err := Parse(c.Plan)
		if (err == nil) != c.Valid {
			t.Fatalf("case %d: acceptance differs from Python: %v", i, err)
		}
		if err == nil {
			accepted = append(accepted, p)
		}
	}
	wire, _ := json.Marshal(accepted)
	if err := os.WriteFile(os.Getenv("SIQ_INSTALL_PLAN_TEST_OUTPUT"), wire, 0600); err != nil {
		t.Fatal(err)
	}
}
