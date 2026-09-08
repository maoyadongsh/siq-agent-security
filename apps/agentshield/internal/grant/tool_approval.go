package grant

import (
	"errors"
	"strings"

	"siq-agent-security/apps/agentshield/internal/signing"
)

// RequireToolApproval only tightens existing pending tool authority.
func RequireToolApproval(g Grant, tools []string, key *signing.Key) (Grant, error) {
	if g.Status != "pending_approval" || len(tools) == 0 || len(tools) > 32 {
		return g, errors.New("grant: invalid tool approval request")
	}
	wanted := map[string]bool{}
	for _, tool := range tools {
		if strings.TrimSpace(tool) == "" || len(tool) > 128 || wanted[tool] {
			return g, errors.New("grant: invalid tool approval request")
		}
		wanted[tool] = true
	}
	for _, f := range g.Facts {
		if f.Domain == "tool" && f.Effect == "allow" && f.State == "declared" {
			delete(wanted, f.Resource.Value)
		}
	}
	if len(wanted) != 0 {
		return g, errors.New("grant: approval tool must already be granted")
	}
	for _, tool := range tools {
		wanted[tool] = true
	}
	g.Facts = append([]Fact(nil), g.Facts...)
	for i, f := range g.Facts {
		if f.Domain == "tool" && f.Effect == "allow" && wanted[f.Resource.Value] {
			conditions := map[string]any{}
			for k, v := range f.Conditions {
				conditions[k] = v
			}
			conditions["require_approval"] = true
			g.Facts[i].Conditions = conditions
		}
	}
	resign(key, &g)
	return g, nil
}
