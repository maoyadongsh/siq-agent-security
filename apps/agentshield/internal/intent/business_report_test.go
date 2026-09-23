package intent

import (
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func TestBusinessReportRequiresExactParametersAndBoundRoot(t *testing.T) {
	c := testContract()
	c.AllowedTools = []string{runtimeaction.ResearchPublishTool}
	c.AllowedEffects = []string{"file.read", "file.write"}
	c.ResourceConstraints = []ResourceConstraint{{Domain: "filesystem", Operator: "equals", Value: runtimeaction.ResearchBusinessRoot}}
	p := map[string]any{"task_id": "task-001", "request_sha256": strings.Repeat("a", 64), "approval_sha256": strings.Repeat("b", 64)}
	for name, value := range p {
		c.ParameterConstraints = append(c.ParameterConstraints, ParameterConstraint{Path: "/" + name, Operator: "equals", Value: value})
	}
	check := func() error {
		return c.Authorize("hermes", "a-1", "u-1", runtimeaction.ResearchPublishTool, p, time.Date(2026, 9, 22, 0, 0, 0, 0, time.UTC))
	}
	if err := check(); err != nil {
		t.Fatal(err)
	}
	p["request_sha256"] = strings.Repeat("c", 64)
	assertCode(t, check(), "intent_parameter_violation")
	p["request_sha256"] = strings.Repeat("a", 64)
	c.ResourceConstraints[0].Value = "/another-root"
	assertCode(t, check(), "intent_resource_not_allowed")
	c.ResourceConstraints[0].Value = runtimeaction.ResearchBusinessRoot
	c.AllowedEffects = []string{"file.read"}
	assertCode(t, check(), "intent_effect_not_allowed")
}
