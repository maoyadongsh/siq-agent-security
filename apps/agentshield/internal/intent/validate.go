package intent

import (
	"encoding/json"
	"net"
	"net/url"
	"path"
	"regexp"
	"strings"
	"time"
)

var idPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$`)
var effects = map[string]bool{"tool.invoke": true, "file.read": true, "file.write": true, "file.delete": true, "network.request": true, "process.exec": true, "message.send": true, "database.read": true, "database.write": true, "secret.read": true, "unknown": true}

func validID(id string) bool { return idPattern.MatchString(id) }
func uniqueNonempty(values []string) bool {
	seen := map[string]bool{}
	for _, v := range values {
		if strings.TrimSpace(v) == "" || seen[v] {
			return false
		}
		seen[v] = true
	}
	return true
}
func (c Contract) Validate() error {
	if c.SchemaVersion != "intent/v2" || !validID(c.IntentID) || c.TaskID == "" || c.Principal.Type != "user" || c.Principal.ID == "" || c.Agent.ID == "" || c.Agent.Platform == "" || c.Purpose == "" || c.Authority.Issuer == "" || c.Authority.Revision == "" {
		return violation("intent_invalid_contract")
	}
	if len(c.AllowedTools) == 0 || len(c.AllowedEffects) == 0 || !uniqueNonempty(c.AllowedTools) || !uniqueNonempty(c.AllowedEffects) || c.ResourceConstraints == nil || c.ParameterConstraints == nil || c.Authority.EvidenceIDs == nil || !uniqueNonempty(c.Authority.EvidenceIDs) {
		return violation("intent_invalid_contract")
	}
	for _, effect := range c.AllowedEffects {
		if !effects[effect] {
			return violation("intent_invalid_effect")
		}
	}
	issued, e1 := time.Parse(time.RFC3339, c.IssuedAt)
	from, e2 := time.Parse(time.RFC3339, c.ValidFrom)
	until, e3 := time.Parse(time.RFC3339, c.ExpiresAt)
	if e1 != nil || e2 != nil || e3 != nil || issued.After(from) || !from.Before(until) {
		return violation("intent_invalid_time_window")
	}
	for _, r := range c.ResourceConstraints {
		if r.Domain != "network" && r.Domain != "filesystem" && r.Domain != "message" {
			return violation("intent_invalid_resource_constraint")
		}
		if err := validateOperator(r.Operator, r.Value, nil, true); err != nil {
			return err
		}
		values := []any{r.Value}
		if r.Operator == "one_of" {
			values, _ = r.Value.([]any)
		}
		for _, value := range values {
			str, ok := value.(string)
			if !ok || str == "" {
				return violation("intent_invalid_resource_constraint")
			}
			if r.Domain == "filesystem" && r.Operator != "regex" && (!path.IsAbs(str) || strings.Contains(str, `\`)) {
				return violation("intent_invalid_resource_constraint")
			}
			if r.Operator == "host" {
				if r.Domain != "network" {
					return violation("intent_invalid_resource_constraint")
				}
				if _, err := normalizeHost(str); err != nil {
					return err
				}
			}
			if r.Operator == "cidr" {
				if r.Domain != "network" {
					return violation("intent_invalid_resource_constraint")
				}
				if _, _, err := net.ParseCIDR(str); err != nil {
					return violation("intent_invalid_resource_constraint")
				}
			}
		}
	}
	for _, p := range c.ParameterConstraints {
		if _, err := pointerParts(p.Path); err != nil {
			return err
		}
		if err := validateOperator(p.Operator, p.Value, p.Values, false); err != nil {
			return err
		}
	}
	return nil
}
func validateOperator(op string, value any, values []any, resource bool) error {
	switch op {
	case "equals":
	case "one_of":
		if resource {
			values, _ = value.([]any)
		}
		if len(values) == 0 {
			return violation("intent_invalid_constraint")
		}
	case "prefix", "suffix", "host", "cidr", "regex":
		str, ok := value.(string)
		if !ok || str == "" {
			return violation("intent_invalid_constraint")
		}
		if !resource && (op == "host" || op == "cidr") {
			return violation("intent_invalid_constraint")
		}
		if op == "regex" {
			if len(str) > 1024 {
				return violation("intent_invalid_regex")
			}
			if _, err := regexp.Compile(str); err != nil {
				return violation("intent_invalid_regex")
			}
		}
	default:
		return violation("intent_invalid_constraint")
	}
	return nil
}
func pointerParts(pointer string) ([]string, error) {
	if len(pointer) > 1024 || !strings.HasPrefix(pointer, "/") {
		return nil, violation("intent_invalid_parameter_pointer")
	}
	parts := strings.Split(pointer[1:], "/")
	for i, p := range parts {
		for j := 0; j < len(p); j++ {
			if p[j] == '~' {
				if j+1 == len(p) || (p[j+1] != '0' && p[j+1] != '1') {
					return nil, violation("intent_invalid_parameter_pointer")
				}
				j++
			}
		}
		parts[i] = strings.ReplaceAll(strings.ReplaceAll(p, "~1", "/"), "~0", "~")
	}
	return parts, nil
}
func normalizeHost(value string) (string, error) {
	if strings.Contains(value, "://") {
		u, err := url.Parse(value)
		if err != nil || u.Hostname() == "" || u.User != nil {
			return "", violation("intent_invalid_host")
		}
		value = u.Hostname()
	}
	value = strings.ToLower(strings.TrimSuffix(value, "."))
	if value == "" {
		return "", violation("intent_invalid_host")
	}
	for _, r := range value {
		if r > 127 || r <= 32 || strings.ContainsRune("/@?#\\", r) {
			return "", violation("intent_invalid_host")
		}
	}
	return value, nil
}
func jsonEqual(a, b any) bool {
	// JSON numbers decoded by HTTP (json.Number) and native callers compare identically.
	aa, e1 := json.Marshal(a)
	bb, e2 := json.Marshal(b)
	return e1 == nil && e2 == nil && string(aa) == string(bb)
}
func (c Contract) Active(now time.Time) error {
	if c.Expired(now) {
		return violation("intent_expired")
	}
	from, err := time.Parse(time.RFC3339, c.ValidFrom)
	if err != nil || now.Before(from) {
		return violation("intent_not_yet_valid")
	}
	return nil
}
