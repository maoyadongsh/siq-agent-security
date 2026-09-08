package runtimeaction

import (
	"fmt"
	"strings"
	"testing"
)

func TestParameterTraversalBudget(t *testing.T) {
	nested := func(n int) map[string]any {
		v := map[string]any{}
		for i := 0; i < n; i++ {
			v = map[string]any{"x": v}
		}
		return v
	}
	for _, tc := range []struct {
		name   string
		params map[string]any
		bad    bool
	}{
		{"depth-limit", nested(64), false}, {"depth-over", nested(65), true},
		{"nodes-limit", map[string]any{"items": make([]any, 8190)}, false},
		{"nodes-over", map[string]any{"items": make([]any, 8191)}, true},
		{"pointer-limit", map[string]any{strings.Repeat("x", 1023): nil}, false},
		{"pointer-over", map[string]any{strings.Repeat("x", 1024): nil}, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			d := Describe("read_file", tc.params)
			if (d.ResourceError != nil && d.ResourceError.Error() == "runtime_parameter_budget_exceeded") != tc.bad {
				t.Fatalf("budget mismatch: %v", d.ResourceError)
			}
			if tc.bad && (len(d.Resources) != 0 || len(d.HighImpactParameterPaths) != 0 || !hasEffect(d.Effects, EffectUnknown)) {
				t.Fatal("partial descriptor escaped")
			}
		})
	}
	wide := map[string]any{}
	for i := 0; i < 2000; i++ {
		wide[strings.Repeat("k", 600)+fmt.Sprint(i)] = nil
	}
	if Describe("read_file", wide).ResourceError != ErrParameterBudget {
		t.Fatal("aggregate pointer budget escaped")
	}
	cyclic := map[string]any{}
	cyclic["self"] = cyclic
	if !(Describe("read_file", cyclic).ResourceError != nil) {
		t.Fatal("cycle escaped")
	}
}
