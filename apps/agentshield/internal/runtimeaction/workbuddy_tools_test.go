package runtimeaction

import "testing"

func TestWorkBuddyPresentationIsNotReadOrTrustedDelivery(t *testing.T) {
	for _, tool := range []string{"present_files", "Glob", "Grep"} {
		d := Describe(tool, map[string]any{"file_path": "/output/report.md", "paths": []any{"/input/private.md", "/output/report.md"}})
		if d.Operation != "invoke" || len(d.Effects) != 1 || d.Effects[0] != EffectUnknown {
			t.Fatalf("%s inferred a supported effect: %+v", tool, d)
		}
	}
	if op, effects := Normalize("Read", map[string]any{"file_path": "/input/report.md"}); op != "read" || len(effects) != 1 || effects[0] != EffectFileRead {
		t.Fatal("supported Read changed")
	}
}
