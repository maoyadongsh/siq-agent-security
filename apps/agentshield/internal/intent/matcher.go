package intent

import (
	"net"
	"regexp"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"strconv"
	"strings"
	"time"
)

func pointerValue(params map[string]any, pointer string) (any, bool) {
	parts, err := pointerParts(pointer)
	if err != nil {
		return nil, false
	}
	var current any = params
	for _, part := range parts {
		switch v := current.(type) {
		case map[string]any:
			var ok bool
			current, ok = v[part]
			if !ok {
				return nil, false
			}
		case []any:
			n, err := strconv.Atoi(part)
			if err != nil || n < 0 || n >= len(v) || strconv.Itoa(n) != part {
				return nil, false
			}
			current = v[n]
		default:
			return nil, false
		}
	}
	return current, true
}
func matches(actual any, op string, wanted any, values []any) bool {
	switch op {
	case "equals":
		return jsonEqual(actual, wanted)
	case "one_of":
		for _, v := range values {
			if jsonEqual(actual, v) {
				return true
			}
		}
		return false
	}
	a, ok := actual.(string)
	w, wok := wanted.(string)
	if !ok || !wok {
		return false
	}
	switch op {
	case "prefix":
		return strings.HasPrefix(a, w)
	case "suffix":
		return strings.HasSuffix(a, w)
	case "regex":
		r, err := regexp.Compile(w)
		return err == nil && len(w) <= 1024 && r.MatchString(a)
	case "host":
		aa, e1 := normalizeHost(a)
		ww, e2 := normalizeHost(w)
		return e1 == nil && e2 == nil && aa == ww
	case "cidr":
		host, err := normalizeHost(a)
		_, network, e2 := net.ParseCIDR(w)
		return err == nil && e2 == nil && network.Contains(net.ParseIP(host))
	}
	return false
}

// Authorize is deterministic and consumes only the verified contract and runtime facts.
func (c Contract) Authorize(platform, agent, principal, tool string, params map[string]any, now time.Time) error {
	if err := c.Validate(); err != nil {
		return err
	}
	if err := c.Active(now); err != nil {
		return err
	}
	if c.Agent.ID != agent || c.Agent.Platform != platform {
		return violation("intent_agent_mismatch")
	}
	if principal != "" && c.Principal.ID != principal {
		return violation("intent_principal_mismatch")
	}
	found := false
	for _, allowed := range c.AllowedTools {
		if allowed == tool {
			found = true
		}
	}
	if !found {
		return violation("intent_tool_not_allowed")
	}
	descriptor := runtimeaction.Describe(tool, params)
	for _, effect := range descriptor.Effects {
		if effect == runtimeaction.EffectUnknown {
			return violation("runtime_effect_unknown")
		}
		found = false
		for _, allowed := range c.AllowedEffects {
			if allowed == effect {
				found = true
			}
		}
		if !found {
			return violation("intent_effect_not_allowed")
		}
	}
	for _, p := range c.ParameterConstraints {
		value, ok := pointerValue(params, p.Path)
		if !ok || !matches(value, p.Operator, p.Value, p.Values) {
			return violation("intent_parameter_violation")
		}
	}
	resources, resourceErr := descriptor.Resources, descriptor.ResourceError
	for _, constraint := range c.ResourceConstraints {
		if resourceErr != nil {
			return violation("intent_resource_not_allowed")
		}
		seen := false
		for _, resource := range resources {
			if resource.Domain != constraint.Domain {
				continue
			}
			seen = true
			if !matchResource(resource, constraint) {
				return violation("intent_resource_not_allowed")
			}
		}
		if !seen {
			return violation("intent_resource_not_allowed")
		}
	}
	return nil
}

func matchResource(resource runtimeaction.Resource, constraint ResourceConstraint) bool {
	normalized := func(wanted any) (string, bool) {
		value, ok := wanted.(string)
		if !ok {
			return "", false
		}
		value, err := runtimeaction.NormalizeResource(resource.Domain, value)
		return value, err == nil
	}
	if constraint.Operator == "equals" || constraint.Operator == "one_of" {
		values := []any{constraint.Value}
		if constraint.Operator == "one_of" {
			values, _ = constraint.Value.([]any)
		}
		for _, value := range values {
			wanted, ok := normalized(value)
			if ok && resource.Value == wanted {
				return true
			}
		}
		return false
	}
	wanted := constraint.Value
	if resource.Domain == "filesystem" && constraint.Operator != "regex" {
		value, ok := normalized(wanted)
		if !ok {
			return false
		}
		wanted = value
		if constraint.Operator == "prefix" {
			return resource.Value == value || strings.HasPrefix(resource.Value, strings.TrimSuffix(value, "/")+"/")
		}
	}
	if resource.Domain == "network" && (constraint.Operator == "prefix" || constraint.Operator == "suffix") {
		value, ok := wanted.(string)
		if !ok {
			return false
		}
		wanted = strings.ToLower(strings.TrimSuffix(value, "."))
	}
	return matches(resource.Value, constraint.Operator, wanted, nil)
}
