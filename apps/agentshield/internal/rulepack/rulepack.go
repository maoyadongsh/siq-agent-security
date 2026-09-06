// Package rulepack loads the signed threat-detection rule pack shared with the
// Python control plane (apps/control-api/app/rulepack.py).
//
// Fail-closed rules mirror the Python side:
//   - the embedded built-in pack is the baseline; a corrupt built-in is a build
//     defect and Load returns an error instead of degrading;
//   - an external pack is used only if it parses, its <file>.sig (base64
//     Ed25519 over the canonical JSON bytes) verifies against the configured
//     public key, and its version is >= the built-in version;
//   - any rejection falls back to the built-in pack and reports only a reason
//     category, never rule contents.
//
// Regex dialect: Go RE2. The shared JSON is kept RE2-compatible (ADR-011 D2);
// a pattern that fails to compile rejects the whole pack.
package rulepack

import (
	"crypto/ed25519"
	_ "embed"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"regexp"
	"strings"

	"siq-agent-security/apps/agentshield/internal/canon"
)

//go:embed data/threat_rules.v1.json
var builtinJSON []byte

// PathEnv mirrors SIQ_AS_THREAT_RULEPACK_PATH on the Python side.
const PathEnv = "SIQ_AS_THREAT_RULEPACK_PATH"

var severities = map[string]bool{"critical": true, "high": true, "medium": true, "low": true}

// Rule is one detection rule with compiled patterns.
type Rule struct {
	ID          string
	Severity    string
	Confidence  float64
	Description string
	Impact      string
	Remediation string
	Patterns    []*regexp.Regexp
}

// Redaction is one excerpt-redaction substitution.
type Redaction struct {
	Pattern     *regexp.Regexp
	Replacement string
}

// Pack is a validated rule pack.
type Pack struct {
	Version    int
	Rules      []Rule
	Redactions []Redaction
	// Source is "builtin" or the external path that was accepted.
	Source string
}

// Error is a pack rejection. Its message is category-only and safe to log.
type Error struct{ msg string }

func (e *Error) Error() string { return e.msg }

func rejectf(format string, a ...any) error { return &Error{msg: fmt.Sprintf(format, a...)} }

// defaultRedactions mirrors _DEFAULT_REDACTION_RULES in rulepack.py and is
// used when an external pack omits redaction_patterns.
var defaultRedactions = []Redaction{
	{regexp.MustCompile(`sk-[a-zA-Z0-9_\-]{8,}`), "sk-***"},
	{regexp.MustCompile(`gh[pousr]_[a-zA-Z0-9]{20,}`), "gh_***"},
	{regexp.MustCompile(`(?i)bearer\s+[a-zA-Z0-9_\-\.]{10,}`), "Bearer ***"},
	{regexp.MustCompile(`(?i)password\s*=\s*['"][^'"]+['"]`), "password=***"},
	{regexp.MustCompile(`(?i)token\s*=\s*['"][^'"]+['"]`), "token=***"},
	{regexp.MustCompile(`(?i)secret\s*=\s*['"][^'"]+['"]`), "secret=***"},
}

// Parse validates and compiles a rule pack document.
func Parse(raw []byte) (*Pack, error) {
	var doc struct {
		Version   json.RawMessage   `json:"version"`
		Rules     []json.RawMessage `json:"rules"`
		Redaction json.RawMessage   `json:"redaction_patterns"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		return nil, rejectf("rulepack root must be an object")
	}
	var version int
	if err := json.Unmarshal(doc.Version, &version); err != nil || version < 1 || strings.ContainsAny(string(doc.Version), ".eE") {
		return nil, rejectf("rulepack 'version' must be a positive integer")
	}
	if len(doc.Rules) == 0 {
		return nil, rejectf("rulepack 'rules' must be a non-empty array")
	}
	seen := map[string]bool{}
	pack := &Pack{Version: version}
	for idx, rr := range doc.Rules {
		var r struct {
			ID          *string   `json:"rule_id"`
			Severity    *string   `json:"severity"`
			Confidence  *float64  `json:"confidence"`
			Description *string   `json:"description"`
			Impact      *string   `json:"impact"`
			Remediation *string   `json:"remediation"`
			Patterns    *[]string `json:"patterns"`
		}
		if err := json.Unmarshal(rr, &r); err != nil {
			return nil, rejectf("rule #%d must be an object with typed fields", idx)
		}
		if r.ID == nil || r.Severity == nil || r.Confidence == nil || r.Description == nil || r.Impact == nil || r.Remediation == nil || r.Patterns == nil {
			return nil, rejectf("rule #%d missing required field(s)", idx)
		}
		if *r.ID == "" || seen[*r.ID] {
			return nil, rejectf("rule #%d has invalid or duplicate rule_id", idx)
		}
		seen[*r.ID] = true
		if !severities[*r.Severity] {
			return nil, rejectf("rule #%d has invalid severity", idx)
		}
		if !(*r.Confidence > 0 && *r.Confidence <= 1) {
			return nil, rejectf("rule #%d has invalid confidence", idx)
		}
		if len(*r.Patterns) == 0 {
			return nil, rejectf("rule #%d 'patterns' must be a non-empty array of strings", idx)
		}
		rule := Rule{
			ID: *r.ID, Severity: *r.Severity, Confidence: *r.Confidence,
			Description: *r.Description, Impact: *r.Impact, Remediation: *r.Remediation,
		}
		for _, p := range *r.Patterns {
			re, err := regexp.Compile(p)
			if err != nil {
				return nil, rejectf("rule #%d contains an uncompilable pattern", idx)
			}
			rule.Patterns = append(rule.Patterns, re)
		}
		pack.Rules = append(pack.Rules, rule)
	}
	red, err := parseRedactions(doc.Redaction)
	if err != nil {
		return nil, err
	}
	pack.Redactions = red
	return pack, nil
}

func parseRedactions(raw json.RawMessage) ([]Redaction, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return defaultRedactions, nil
	}
	var items []struct {
		Pattern     *string `json:"pattern"`
		Replacement *string `json:"replacement"`
	}
	if err := json.Unmarshal(raw, &items); err != nil || len(items) == 0 {
		return nil, rejectf("rulepack 'redaction_patterns' must be a non-empty array when present")
	}
	out := make([]Redaction, 0, len(items))
	for idx, it := range items {
		if it.Pattern == nil || *it.Pattern == "" {
			return nil, rejectf("redaction_patterns #%d missing non-empty string 'pattern'", idx)
		}
		if it.Replacement == nil {
			return nil, rejectf("redaction_patterns #%d missing string 'replacement'", idx)
		}
		re, err := regexp.Compile(*it.Pattern)
		if err != nil {
			return nil, rejectf("redaction_patterns #%d contains an uncompilable pattern", idx)
		}
		out = append(out, Redaction{re, *it.Replacement})
	}
	return out, nil
}

// Builtin returns the embedded pack. A parse failure is a build defect.
func Builtin() (*Pack, error) {
	p, err := Parse(builtinJSON)
	if err != nil {
		return nil, fmt.Errorf("built-in threat rulepack is corrupt (build defect): %w", err)
	}
	p.Source = "builtin"
	return p, nil
}

// BuiltinBytes exposes the embedded document for parity tests.
func BuiltinBytes() []byte { return builtinJSON }

// VerifySignature checks <path>.sig (base64 Ed25519) over the canonical bytes
// of the document at path.
func VerifySignature(pub ed25519.PublicKey, path string, raw []byte) error {
	sigB64, err := os.ReadFile(path + ".sig")
	if err != nil {
		return rejectf("missing signature file (.sig)")
	}
	sig, err := base64.StdEncoding.Strict().DecodeString(strings.TrimSpace(string(sigB64)))
	if err != nil {
		return rejectf("signature file is not valid base64")
	}
	v, err := canon.Decode(raw)
	if err != nil {
		return rejectf("rulepack is not valid JSON")
	}
	msg, err := canon.Marshal(v)
	if err != nil {
		return rejectf("rulepack cannot be canonicalised")
	}
	if len(pub) != ed25519.PublicKeySize || !ed25519.Verify(pub, msg, sig) {
		return rejectf("signature verification failed")
	}
	return nil
}

// Load returns the effective pack: the external pack named by PathEnv when it
// parses, verifies against pub and is not a downgrade; otherwise the built-in.
// warn receives a category-only reason whenever the external pack is rejected.
func Load(pub ed25519.PublicKey, warn func(string)) (*Pack, error) {
	builtin, err := Builtin()
	if err != nil {
		return nil, err
	}
	path := os.Getenv(PathEnv)
	if path == "" {
		return builtin, nil
	}
	if warn == nil {
		warn = func(string) {}
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		warn("external rulepack unreadable; using builtin")
		return builtin, nil
	}
	ext, err := Parse(raw)
	if err != nil {
		warn("external rulepack rejected (" + err.Error() + "); using builtin")
		return builtin, nil
	}
	if len(pub) == 0 {
		warn("external rulepack rejected (no verification key); using builtin")
		return builtin, nil
	}
	if err := VerifySignature(pub, path, raw); err != nil {
		warn("external rulepack rejected (" + err.Error() + "); using builtin")
		return builtin, nil
	}
	if isDowngrade(ext, builtin) {
		warn("external rulepack rejected (version downgrade); using builtin")
		return builtin, nil
	}
	ext.Source = path
	return ext, nil
}

// isDowngrade mirrors the Python anti-rollback rule: an external pack older
// than the built-in is refused; an equal version is accepted.
func isDowngrade(ext, builtin *Pack) bool { return ext.Version < builtin.Version }

// ErrRejected reports whether err is a pack rejection (as opposed to a build defect).
func ErrRejected(err error) bool {
	var e *Error
	return errors.As(err, &e)
}
