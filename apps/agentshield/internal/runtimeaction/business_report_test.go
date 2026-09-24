package runtimeaction

import (
	"encoding/json"
	"os"
	"testing"
)

func TestBusinessReportSharedContractCases(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/contracts/siq-research-business-call-v1-cases.json")
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
	for _, tc := range cases {
		t.Run(tc.Name, func(t *testing.T) {
			d := Describe(tc.Call.Tool, tc.Call.Params)
			if hasEffect(d.Effects, EffectUnknown) == tc.Valid {
				t.Fatal("effect classification differs from contract", d)
			}
			if !tc.Valid {
				return
			}
			if d.ResourceError != nil || len(d.Resources) != 1 || d.Resources[0].Domain != "filesystem" || d.Resources[0].Value != ResearchBusinessRoot || len(d.Paths) != 1 || d.Paths[0] != ResearchBusinessRoot {
				t.Fatal("fixed implementation root lost", d)
			}
			if d.ShellLike || d.Egress || len(d.Hosts) != 0 || len(d.HighImpactParameterPaths) != len(tc.Call.Params) {
				t.Fatal("unexpected effects or missing provenance", d)
			}
			if d.Mutating != (tc.Call.Tool == ResearchPublishTool) || d.FilesystemWriteHint != d.Mutating {
				t.Fatal("write classification lost", d)
			}
		})
	}
}
