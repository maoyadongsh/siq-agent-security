package intent

import (
	"testing"
	"time"
)

func TestNativeSkillLoaderPreservesEveryIntentConstraint(t *testing.T) {
	now := time.Date(2026, 10, 7, 0, 0, 0, 0, time.UTC)
	for _, name := range []string{"valid", "wrong-agent", "wrong-principal", "wrong-tool", "wrong-effect", "expired", "parameter", "resource", "ordinary-entry"} {
		t.Run(name, func(t *testing.T) {
			c := testContract()
			c.AllowedTools, c.AllowedEffects = []string{"skill_view"}, []string{"tool.invoke"}
			agent, principal := "a-1", "u-1"
			params := map[string]any{"name": "reader"}
			switch name {
			case "wrong-agent":
				agent = "a-2"
			case "wrong-principal":
				principal = "u-2"
			case "wrong-tool":
				c.AllowedTools = []string{"read_file"}
			case "wrong-effect":
				c.AllowedEffects = []string{"file.read"}
			case "expired":
				c.ExpiresAt = "2026-02-01T00:00:00Z"
			case "parameter":
				c.ParameterConstraints = []ParameterConstraint{{Path: "/name", Operator: "equals", Value: "different"}}
			case "resource":
				c.ResourceConstraints = []ResourceConstraint{{Domain: "filesystem", Operator: "equals", Value: "/unrelated"}}
			}
			var err error
			if name == "ordinary-entry" {
				err = c.Authorize("hermes", agent, principal, "skill_view", params, now)
			} else {
				err = c.AuthorizeNativeSkillLoad("hermes", agent, principal, "skill_view", params, now)
			}
			if (err == nil) != (name == "valid") {
				t.Fatal("intent constraint lost", name, err)
			}
		})
	}
}
