package inventory

import (
	"sort"
	"strings"
)

// extractConfigFacts copies the stdlib YAML skim from connectors/hermes
// (package main, not importable): model.default, provider, platform_toolsets/toolsets.
func extractConfigFacts(data []byte) (model, provider string, toolsets []string) {
	lines := strings.Split(string(data), "\n")
	inModel := false
	inToolsets := false
	seen := map[string]bool{}
	for _, raw := range lines {
		line := strings.TrimRight(raw, "\r")
		trimmed := strings.TrimSpace(line)
		if trimmed == "" || strings.HasPrefix(trimmed, "#") {
			continue
		}
		indent := len(line) - len(strings.TrimLeft(line, " "))
		isItem := strings.HasPrefix(trimmed, "-")
		if indent == 0 && !isItem {
			inModel = false
			inToolsets = false
		}
		switch {
		case trimmed == "model:":
			inModel = true
			inToolsets = false
		case inModel && strings.HasPrefix(trimmed, "default:"):
			model = yamlScalar(strings.TrimPrefix(trimmed, "default:"))
		case indent == 0 && strings.HasPrefix(trimmed, "provider:"):
			provider = yamlScalar(strings.TrimPrefix(trimmed, "provider:"))
		case indent == 0 && (trimmed == "platform_toolsets:" || trimmed == "toolsets:"):
			inToolsets = true
			inModel = false
		case inToolsets && isItem:
			key := yamlScalar(strings.TrimPrefix(trimmed, "-"))
			if i := strings.Index(key, ":"); i >= 0 {
				key = strings.TrimSpace(key[i+1:])
			}
			if key != "" && !looksLikeSecret(key) {
				seen[key] = true
			}
		}
	}
	for k := range seen {
		toolsets = append(toolsets, k)
	}
	sort.Strings(toolsets)
	return model, provider, toolsets
}

// extractToolsetModeKeys reads platform_toolset_modes keys only (values unused).
func extractToolsetModeKeys(data []byte) []string {
	lines := strings.Split(string(data), "\n")
	in := false
	seen := map[string]bool{}
	for _, raw := range lines {
		line := strings.TrimRight(raw, "\r")
		trimmed := strings.TrimSpace(line)
		if trimmed == "" || strings.HasPrefix(trimmed, "#") {
			continue
		}
		indent := len(line) - len(strings.TrimLeft(line, " "))
		if indent == 0 && !strings.HasPrefix(trimmed, "-") {
			in = trimmed == "platform_toolset_modes:" || strings.HasPrefix(trimmed, "platform_toolset_modes:")
			if in && strings.Contains(trimmed, ":") && trimmed != "platform_toolset_modes:" {
				in = false
			}
			continue
		}
		if !in || indent == 0 {
			continue
		}
		key, _, ok := strings.Cut(trimmed, ":")
		key = yamlScalar(key)
		if ok && key != "" && !looksLikeSecret(key) {
			seen[key] = true
		}
	}
	out := make([]string, 0, len(seen))
	for k := range seen {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func yamlScalar(v string) string {
	v = strings.TrimSpace(v)
	if i := strings.Index(v, " #"); i >= 0 {
		v = strings.TrimSpace(v[:i])
	}
	if len(v) >= 2 && ((v[0] == '"' && v[len(v)-1] == '"') || (v[0] == '\'' && v[len(v)-1] == '\'')) {
		v = v[1 : len(v)-1]
	}
	return v
}

func looksLikeSecret(s string) bool {
	l := strings.ToLower(s)
	if strings.Contains(l, "key") || strings.Contains(l, "token") || strings.Contains(l, "secret") || strings.Contains(l, "password") {
		return true
	}
	return len(s) >= 24 && strings.ContainsAny(s, "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
}

func joinCSV(ss []string) string {
	return strings.Join(ss, ",")
}
