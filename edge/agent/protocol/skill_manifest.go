package protocol

import (
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"
)

const MaxSkillManifestBytes = 256 * 1024

// SkillManifest is declaration metadata only, never an authority or safety verdict.
type SkillManifest struct {
	Status              string   `json:"status"`
	ContentSHA256       string   `json:"content_sha256,omitempty"`
	Name                string   `json:"name,omitempty"`
	AllowedToolsPresent bool     `json:"allowed_tools_present"`
	DeclaredTools       []string `json:"declared_tools"`
}

var skillMachineName = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$`)
var skillDeclarationRedactor = NewRedactor()

func validSkillMachineName(value string) bool {
	return skillMachineName.MatchString(value) && skillDeclarationRedactor.RedactString(value) == value
}

// ParseSkillManifest has no filesystem/process/network operations. Unsupported
// syntax discards all partial declarations, not just the offending field.
func ParseSkillManifest(data []byte) SkillManifest {
	result := SkillManifest{Status: "too_large", DeclaredTools: []string{}}
	if len(data) > MaxSkillManifestBytes {
		return result
	}
	result.ContentSHA256 = ContentHash(data)
	result.Status = "invalid_utf8"
	if !utf8.Valid(data) {
		return result
	}
	result.Status = "missing_frontmatter"
	lines := strings.Split(strings.ReplaceAll(string(data), "\r\n", "\n"), "\n")
	if len(lines) == 0 || lines[0] != "---" {
		return result
	}
	result.Status = "unsupported"
	name, active := "", ""
	seen := map[string]bool{}
	tools := map[string]bool{}
	count := 0
	add := func(raw string) bool {
		value := skillScalar(raw)
		if !validSkillMachineName(value) {
			return false
		}
		count++
		if count > 64 {
			return false
		}
		tools[value] = true
		return true
	}
	for _, line := range lines[1:] {
		if line == "---" {
			if name == "" {
				return result
			}
			result.Status, result.Name = "parsed", name
			result.AllowedToolsPresent = seen["allowed-tools"]
			for tool := range tools {
				result.DeclaredTools = append(result.DeclaredTools, tool)
			}
			sort.Strings(result.DeclaredTools)
			return result
		}
		trimmed := strings.TrimSpace(line)
		if trimmed == "" || strings.HasPrefix(trimmed, "#") {
			continue
		}
		if strings.HasPrefix(line, " ") || strings.HasPrefix(line, "\t") {
			if active == "allowed-tools" {
				if !strings.HasPrefix(trimmed, "- ") || !add(strings.TrimSpace(trimmed[2:])) {
					return result
				}
			} else if active == "name" {
				return result
			}
			continue
		}
		key, value, ok := strings.Cut(line, ":")
		if !ok {
			return result
		}
		key, value = strings.TrimSpace(key), strings.TrimSpace(value)
		if normalized := skillScalar(key); normalized != key && (normalized == "name" || normalized == "allowed-tools") {
			return result // Quoted target keys are outside this parser's subset.
		}
		active = key
		if key != "name" && key != "allowed-tools" {
			continue
		}
		if seen[key] {
			return result
		}
		seen[key] = true
		if key == "name" {
			name = skillScalar(value)
			if !validSkillMachineName(name) {
				return result
			}
			continue
		}
		if value == "" {
			continue
		}
		if strings.HasPrefix(value, "[") {
			if !strings.HasSuffix(value, "]") {
				return result
			}
			value = strings.TrimSpace(value[1 : len(value)-1])
			if value != "" {
				for _, item := range strings.Split(value, ",") {
					if !add(strings.TrimSpace(item)) {
						return result
					}
				}
			}
		} else {
			value = skillScalar(value)
			for _, tool := range strings.FieldsFunc(value, func(r rune) bool { return r == ' ' || r == '\t' || r == ',' }) {
				if !add(tool) {
					return result
				}
			}
		}
		// A scalar/list already supplied cannot also start a block sequence.
		active = "name"
	}
	return result
}

func skillScalar(value string) string {
	if len(value) >= 2 && (value[0] == '\'' && value[len(value)-1] == '\'' || value[0] == '"' && value[len(value)-1] == '"') {
		return value[1 : len(value)-1]
	}
	return value
}
