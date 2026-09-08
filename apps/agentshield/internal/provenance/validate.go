package provenance

import (
	"crypto/sha256"
	"encoding/hex"
	"regexp"
	"siq-agent-security/apps/agentshield/internal/canon"
	"strconv"
	"strings"
)

var sourceTypes = map[string]bool{"USER": true, "SYSTEM": true, "TRUSTED_IAM": true, "TRUSTED_DATABASE": true, "MCP": true, "WEB": true, "TOOL": true, "MEMORY": true, "AGENT": true, "SECRET": true, "CONFIDENTIAL": true, "UNKNOWN": true}
var trustRanks = map[string]int{"unknown": 0, "untrusted": 1, "trusted": 2, "authoritative": 3}
var pointerPattern = regexp.MustCompile(`^(?:/(?:[^~]|~[01])*)+$`)

// ValidateReport enforces the ceiling for unprivileged reports; it does not
// issue or authenticate an assertion.
func ValidateReport(source Source) error {
	switch source.Type {
	case "MCP", "WEB", "TOOL", "AGENT", "UNKNOWN":
	default:
		return failure("provenance_authority_invalid")
	}
	if source.SourceID == "" || len(source.SourceID) > 256 || source.Trust != "unknown" && source.Trust != "untrusted" {
		return failure("provenance_authority_invalid")
	}
	return nil
}
func ContentDigest(value any) (string, error) {
	b, err := canon.Marshal(value)
	if err != nil {
		return "", failure("provenance_content_invalid")
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:]), nil
}
func PointerValue(value any, pointer string) (any, bool) {
	if len(pointer) > 1024 || !pointerPattern.MatchString(pointer) {
		return nil, false
	}
	for _, part := range strings.Split(pointer[1:], "/") {
		key := strings.ReplaceAll(strings.ReplaceAll(part, "~1", "/"), "~0", "~")
		switch v := value.(type) {
		case map[string]any:
			var ok bool
			value, ok = v[key]
			if !ok {
				return nil, false
			}
		case []any:
			i, err := strconv.Atoi(key)
			if err != nil || i < 0 || i >= len(v) || strconv.Itoa(i) != key {
				return nil, false
			}
			value = v[i]
		default:
			return nil, false
		}
	}
	return value, true
}
func (c Constraint) Validate() error {
	if len(c.ParameterPath) > 1024 || !pointerPattern.MatchString(c.ParameterPath) || len(c.AllowedSourceTypes) == 0 || len(c.AllowedSourceTypes) > len(sourceTypes) {
		return failure("provenance_constraint_invalid")
	}
	if _, ok := trustRanks[c.MinimumTrust]; !ok {
		return failure("provenance_constraint_invalid")
	}
	seen := map[string]bool{}
	for _, s := range c.AllowedSourceTypes {
		if !sourceTypes[s] || seen[s] {
			return failure("provenance_constraint_invalid")
		}
		seen[s] = true
	}
	return nil
}
