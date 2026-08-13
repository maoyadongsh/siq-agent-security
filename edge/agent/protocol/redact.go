package protocol

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"regexp"
	"strings"
)

// ErrEnvFileRefused is returned by RedactFileContent for .env files. Security
// invariant: .env content must NEVER be processed or uploaded (contract §4
// negative test); connectors must emit a secret_ref evidence that carries only
// the file name and size instead.
var ErrEnvFileRefused = errors.New("redaction: refusing to process .env content")

// ContentHash returns the hex sha256 of data. Contract: evidence.content_hash
// is the sha256 of the normalized original evidence content.
func ContentHash(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

// IsEnvFile reports whether name looks like an environment-secrets file
// (.env, .env.local, .env.production, foo.env).
func IsEnvFile(name string) bool {
	n := strings.ToLower(name)
	return n == ".env" || strings.HasPrefix(n, ".env.") || strings.HasSuffix(n, ".env")
}

// Redactor implements the siq.redaction.v1 profile: regex-based removal of
// common token/secret shapes. It is shared by the connectors (they must never
// emit raw tokens in any field) and by the Edge (defense in depth over
// connector output).
type Redactor struct {
	rules []*regexp.Regexp
}

// NewRedactor builds the siq.redaction.v1 rule set.
func NewRedactor() *Redactor {
	return &Redactor{rules: []*regexp.Regexp{
		regexp.MustCompile(`(?i)(?:sk|pk)-[A-Za-z0-9_\-]{12,}`),              // OpenAI-style keys
		regexp.MustCompile(`(?i)(?:api[_-]?key|apikey)\s*[:=]\s*[^\s,;"]{4,}`), // api_key=...
		regexp.MustCompile(`(?i)(?:password|passwd|pwd)\s*[:=]\s*[^\s,;"]{4,}`),
		regexp.MustCompile(`(?i)(?:secret|token)\s*[:=]\s*[^\s,;"]{4,}`),
		regexp.MustCompile(`Bearer\s+[A-Za-z0-9._~+/=#-]{4,}`), // Authorization headers
		regexp.MustCompile(`AKIA[0-9A-Z]{16}`),                 // AWS access key
		regexp.MustCompile(`ghp_[A-Za-z0-9]{36}`),              // GitHub PAT
		regexp.MustCompile(`(?s)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----`),
	}}
}

// RedactString replaces every match of the profile's rules with [REDACTED].
func (r *Redactor) RedactString(s string) string {
	for _, rx := range r.rules {
		s = rx.ReplaceAllString(s, "[REDACTED]")
	}
	return s
}

// RedactFileContent redacts file content. Files named .env/.env.* are refused
// outright (see ErrEnvFileRefused); everything else is passed through
// RedactString. Note: connectors in this repo never upload file content
// (payload_ref stays null) — this gate exists so a future payload upload path
// cannot leak secrets.
func (r *Redactor) RedactFileContent(name string, content []byte) ([]byte, error) {
	if IsEnvFile(name) {
		return nil, ErrEnvFileRefused
	}
	return []byte(r.RedactString(string(content))), nil
}
