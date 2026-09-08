// Package trustedcontext validates signed observations without granting rights.
package trustedcontext

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"regexp"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/signing"
)

type Subject struct {
	Platform  string `json:"platform"`
	SessionID string `json:"session_id"`
	AgentID   string `json:"agent_id"`
}
type Claims struct {
	WorkspaceRoot string `json:"workspace_root"`
}
type Assertion struct {
	SchemaVersion  string  `json:"schema_version"`
	AssertionID    string  `json:"assertion_id"`
	IssuerID       string  `json:"issuer_id"`
	Subject        Subject `json:"subject"`
	TaskID         string  `json:"task_id"`
	Claims         Claims  `json:"claims"`
	IssuedAt       string  `json:"issued_at"`
	ExpiresAt      string  `json:"expires_at"`
	RequestBinding string  `json:"request_binding"`
	SigningSchema  string  `json:"signing_schema"`
	Signature      string  `json:"signature"`
}
type Violation struct{ Code string }

func (v *Violation) Error() string { return v.Code }
func invalid() error               { return &Violation{Code: "trusted_context_invalid"} }

var idPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)
var digestPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

// RequestBinding is scoped to a single identified call. It contains no authority
// claims and cannot be used to mint an assertion.
func RequestBinding(subject Subject, task, tool, call string, params map[string]any) (string, error) {
	if subject.Platform == "" || subject.SessionID == "" || subject.AgentID == "" || task == "" || tool == "" || call == "" || params == nil {
		return "", invalid()
	}
	b, err := canon.Marshal(map[string]any{"platform": subject.Platform, "session_id": subject.SessionID, "agent_id": subject.AgentID, "task_id": task, "tool": tool, "tool_call_id": call, "params": params})
	if err != nil {
		return "", invalid()
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:]), nil
}
func (a Assertion) Validate() error {
	if a.SchemaVersion != "context-assertion/v1" || !idPattern.MatchString(a.AssertionID) || a.IssuerID != "local-admin" || a.SigningSchema != signing.SchemaLocalCanonicalV1 || !digestPattern.MatchString(a.RequestBinding) {
		return invalid()
	}
	for _, field := range []string{a.Subject.Platform, a.Subject.SessionID, a.Subject.AgentID, a.TaskID} {
		if field == "" || len(field) > 256 {
			return invalid()
		}
	}
	normalized, err := runtimeaction.NormalizeResource("filesystem", a.Claims.WorkspaceRoot)
	if err != nil || normalized != a.Claims.WorkspaceRoot || len(normalized) > 4096 {
		return invalid()
	}
	issued, err := time.Parse(time.RFC3339, a.IssuedAt)
	expires, endErr := time.Parse(time.RFC3339, a.ExpiresAt)
	if err != nil || endErr != nil || !issued.Before(expires) {
		return invalid()
	}
	return nil
}
func (a Assertion) Unsigned() map[string]any {
	b, _ := json.Marshal(a)
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	delete(m, "signature")
	return m
}

// Check follows signature verification by the trusted store. A workspace claim
// is intentionally not returned as a Grant or used to broaden resource scopes.
func (a Assertion) Check(subject Subject, task, tool, call string, params map[string]any, now time.Time) error {
	if err := a.Validate(); err != nil {
		return err
	}
	issued, _ := time.Parse(time.RFC3339, a.IssuedAt)
	expires, _ := time.Parse(time.RFC3339, a.ExpiresAt)
	if now.Before(issued) {
		return invalid()
	}
	if !now.Before(expires) {
		return &Violation{Code: "trusted_context_expired"}
	}
	bound, err := RequestBinding(subject, task, tool, call, params)
	if err != nil || a.Subject != subject || a.TaskID != task || a.RequestBinding != bound {
		return &Violation{Code: "trusted_context_scope_mismatch"}
	}
	return nil
}
