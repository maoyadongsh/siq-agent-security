package runtimeaction

import "testing"

func TestReportVerificationIsClosedAndDoesNotRelaxShell(t *testing.T) {
	d := Describe("verify_report", map[string]any{"path": "/workspace/report.md"})
	if d.ResourceError != nil || len(d.Resources) != 1 || d.Resources[0].Domain != "filesystem" || !hasEffect(d.Effects, EffectProcessExec) || hasEffect(d.Effects, EffectUnknown) || len(d.HighImpactParameterPaths) != 1 || d.HighImpactParameterPaths[0] != "/path" {
		t.Fatal(d)
	}
	for _, params := range []map[string]any{{}, {"path": "relative"}, {"path": true}, {"path": "/workspace/report.md", "command": "echo smuggled"}} {
		if !hasEffect(Describe("verify_report", params).Effects, EffectUnknown) {
			t.Fatal("invalid shape accepted")
		}
	}
	for _, name := range []string{"exec", "shell", "python"} {
		if !hasEffect(Describe(name, map[string]any{"path": "/workspace/report.md"}).Effects, EffectUnknown) {
			t.Fatal("opaque interpreter relaxed")
		}
	}
}
