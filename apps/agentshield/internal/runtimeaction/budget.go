package runtimeaction

import (
	"errors"
	"strings"
)

var ErrParameterBudget = errors.New("runtime_parameter_budget_exceeded")

// ValidateParameters bounds traversal before any recursive normalization. Nodes
// include the root and scalar values; pointer bytes include JSON escaping.
func ValidateParameters(params map[string]any) error {
	nodes, total := 0, 0
	var walk func(any, int, int) error
	walk = func(value any, depth, pointerBytes int) error {
		nodes++
		total += pointerBytes
		if depth > 64 || nodes > 8192 || pointerBytes > 1024 || total > 1<<20 {
			return ErrParameterBudget
		}
		switch v := value.(type) {
		case map[string]any:
			if len(v) > 8192-nodes {
				return ErrParameterBudget
			}
			for k, x := range v {
				size := len(k) + strings.Count(k, "~") + strings.Count(k, "/")
				if err := walk(x, depth+1, pointerBytes+1+size); err != nil {
					return err
				}
			}
		case []any:
			if len(v) > 8192-nodes {
				return ErrParameterBudget
			}
			for i, x := range v {
				digits := 1
				for n := i; n >= 10; n /= 10 {
					digits++
				}
				if err := walk(x, depth+1, pointerBytes+1+digits); err != nil {
					return err
				}
			}
		}
		return nil
	}
	return walk(params, 0, 0)
}
