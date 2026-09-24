package runtimeaction

import (
	"encoding/json"
	"os"
	"testing"
)

func TestReportGenerationSharedCases(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/contracts/siq-research-report-generation-call-v1-cases.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name  string
		Valid bool
		Call  struct {
			Tool   string
			Params map[string]any
		}
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	for _, c := range cases {
		t.Run(c.Name, func(t *testing.T) {
			d := Describe(c.Call.Tool, c.Call.Params)
			if hasEffect(d.Effects, EffectUnknown) == c.Valid {
				t.Fatal("classification differs from contract", d)
			}
			if !c.Valid {
				return
			}
			if d.ResourceError != nil || len(d.Paths) != 3 || len(d.Resources) != 4 || d.ShellLike || !d.Egress || !d.Mutating {
				t.Fatal(d)
			}
			if !d.ReadOnlyPaths[d.Paths[0]] || !d.ReadOnlyPaths[d.Paths[1]] || d.ReadOnlyPaths[d.Paths[2]] || len(d.HighImpactParameterPaths) != 3 {
				t.Fatal("incorrect per-path effect", d)
			}
			if len(d.Hosts) != 1 || d.Hosts[0] != ResearchGenerateBroker {
				t.Fatal(d)
			}
		})
	}
}

func TestGenerationDoesNotBlessTerminalOrWindowsPaths(t *testing.T) {
	if !hasEffect(Describe("terminal", map[string]any{"command": "python run_analysis_report.py"}).Effects, EffectUnknown) {
		t.Fatal("terminal exemption")
	}
	p := map[string]any{"company_path": "/project/data/wiki/companies/600418-example", "run_id": "qwen-request-0123456789abcdef", "year": 2025}
	if DescribeForProfile(FilesystemWindowsLocalDriveV1, ResearchGenerateTool, p).ResourceError == nil {
		t.Fatal("unsupported filesystem accepted")
	}
}
