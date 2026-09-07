package intent

import (
	"net"
	"path"
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
	_, requested := runtimeaction.Normalize(tool, params)
	for _, effect := range requested {
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
	for _, r := range c.ResourceConstraints {
		// Shell and opaque tools have no trusted resource extraction: fail closed.
		keys := []string{}
		switch r.Domain {
		case "filesystem":
			if requested[0] == "file.read" || requested[0] == "file.write" || requested[0] == "file.delete" {
				keys = []string{"path", "file_path"}
			}
		case "network":
			if requested[0] == "network.request" {
				keys = []string{"url", "host"}
			}
		case "message":
			if requested[0] == "message.send" {
				keys = []string{"recipient", "to"}
			}
		}
		seen := false
		for _, key := range keys {
			raw, ok := params[key]
			if !ok {
				continue
			}
			seen = true
			value, ok := raw.(string)
			if !ok {
				return violation("intent_resource_not_allowed")
			}
			wanted := r.Value
			values, _ := r.Value.([]any)
			if r.Domain == "filesystem" {
				if !path.IsAbs(value) || strings.Contains(value, `\`) {
					return violation("intent_resource_not_allowed")
				}
				value = path.Clean(value)
				if w, ok := wanted.(string); ok && r.Operator != "regex" {
					wanted = path.Clean(w)
				}
				if r.Operator == "prefix" {
					w := wanted.(string)
					if value != w && !strings.HasPrefix(value, strings.TrimSuffix(w, "/")+"/") {
						return violation("intent_resource_not_allowed")
					}
					continue
				}
			}
			if r.Domain == "network" {
				var err error
				value, err = normalizeHost(value)
				if err != nil {
					return violation("intent_resource_not_allowed")
				}
			}
			if !matches(value, r.Operator, wanted, values) {
				return violation("intent_resource_not_allowed")
			}
		}
		if !seen {
			return violation("intent_resource_not_allowed")
		}
	}
	return nil
}
