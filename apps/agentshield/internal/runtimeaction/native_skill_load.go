package runtimeaction

import "strings"

// This is an invocation of the verified native loader, not generic file I/O.
// Caller must have verified a live native call. Actual bytes remain withheld
// until NativeHost.Load validates their signed
// installation and source. Never apply this to an ordinary same-named tool.
func ProtectedSkillLoadDescriptor(platform, tool string, params map[string]any) (Descriptor, bool) {
	if platform != "hermes" || tool != "skill_view" || len(params) < 1 || len(params) > 2 {
		return Descriptor{}, false
	}
	for key, value := range params {
		if key != "name" && key != "file_path" {
			return Descriptor{}, false
		}
		text, ok := value.(string)
		if !ok || text == "" || len(text) > 4096 || strings.Contains(text, "\\") || strings.HasPrefix(text, "/") {
			return Descriptor{}, false
		}
		for _, r := range text {
			if r < 32 || r == 127 {
				return Descriptor{}, false
			}
		}
		parts := strings.Split(text, "/")
		if len(parts) > 128 {
			return Descriptor{}, false
		}
		for _, part := range parts {
			if part == "" || part == "." || part == ".." {
				return Descriptor{}, false
			}
		}
	}
	if _, ok := params["name"]; !ok {
		return Descriptor{}, false
	}
	return Descriptor{Tool: tool, Operation: "skill.load", Effects: []string{EffectToolInvoke}}, true
}
