package provenance

import (
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"testing"
)

func TestHighImpactDefaultsAndExplicitPermission(t *testing.T) {
	params := map[string]any{"recipient": "a", "destination_host": "b", "url": "https://example.test", "filesystem_target": "/work", "database_scope": "tenant", "credential_ref": "vault", "deployment_target": "dev", "repo": "r", "branch": "b", "command": "echo", "account": "a", "identity": "i"}
	d := runtimeaction.Describe("unknown_tool", params)
	defaults := ConstraintsForAction(nil, d)
	if len(defaults) != 12 {
		t.Fatal("missing required taxonomy coverage", defaults)
	}
	for _, c := range defaults {
		if !c.Required || c.MinimumTrust != "trusted" || c.Validate() != nil {
			t.Fatal("weak default", c)
		}
	}
	explicit := []Constraint{{ParameterPath: "/recipient", AllowedSourceTypes: []string{"MCP"}, MinimumTrust: "untrusted", Required: true}}
	out := ConstraintsForAction(explicit, d)
	if len(out) != 12 || len(explicit) != 1 || out[0].AllowedSourceTypes[0] != "MCP" {
		t.Fatal("explicit signed permission lost", out)
	}
	count := 0
	for _, c := range out {
		if c.ParameterPath == "/recipient" {
			count++
		}
	}
	if count != 1 {
		t.Fatal("explicit constraint did not replace default")
	}
}
