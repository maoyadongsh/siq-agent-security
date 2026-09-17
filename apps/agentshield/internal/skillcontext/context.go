// Package skillcontext issues and verifies skill execution contexts (SEC,
// contract skill-execution-context/v1). A SEC is the only path that raises
// skill attribution from unknown to verified; it grants no rights by itself
// and never widens resource scopes. The signing private key stays in the
// state directory; adapters and UI never hold it.
//
// Threat scope (docs/personal-experience-n05-trusted-skill-execution-spec.md
// §1): SECs defeat forgery by model-controlled input and by other skills at
// the call layer. They do not defend against a compromised host or malicious
// same-UID local code.
package skillcontext

import (
	"encoding/json"
	"regexp"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
)

// Schema and issuer constants are part of the signed contract.
const (
	Schema           = "skill-execution-context/v1"
	RevocationSchema = "skill-execution-context-revocation/v1"
	Issuer           = "local-admin"
	EvidenceTask     = "controlled_task"
	EvidenceSession  = "controlled_session"
	MaxTTL           = 24 * time.Hour
	maxContexts      = 256
	maxContextBytes  = 16 << 10
)

// Subject pins a SEC to one managed instance session (and task when the host
// supplies one). Every component must match the decision request exactly.
type Subject struct {
	Platform   string `json:"platform"`
	InstanceID string `json:"instance_id"`
	AgentID    string `json:"agent_id"`
	SessionID  string `json:"session_id"`
	TaskID     string `json:"task_id,omitempty"`
}

// SkillRef is the exact approved skill identity (skill id + content hash,
// plus version when the grant pins one).
type SkillRef struct {
	SkillID     string `json:"skill_id"`
	Version     string `json:"version,omitempty"`
	ContentHash string `json:"content_hash"`
}

// InstallRef binds the SEC to the signed install record read at issuance.
type InstallRef struct {
	InstallID      string `json:"install_id"`
	ClaimSignature string `json:"claim_signature"`
}

// AuthorityRef binds the SEC to one grant and its canonical digest computed
// by the issuer. Any revision, revocation or status flip changes the digest.
type AuthorityRef struct {
	GrantID     string `json:"grant_id"`
	GrantDigest string `json:"grant_digest"`
}

// Context is the signed skill-execution-context/v1 document.
type Context struct {
	SchemaVersion string       `json:"schema_version"`
	ContextID     string       `json:"context_id"`
	IssuerID      string       `json:"issuer_id"`
	Subject       Subject      `json:"subject"`
	Skill         SkillRef     `json:"skill"`
	Install       InstallRef   `json:"install"`
	Authority     AuthorityRef `json:"authority"`
	EvidenceLevel string       `json:"evidence_level"`
	IssuedAt      string       `json:"issued_at"`
	ExpiresAt     string       `json:"expires_at"`
	SigningSchema string       `json:"signing_schema"`
	Signature     string       `json:"signature"`
}

// Revocation is the signed tombstone that invalidates a SEC without deleting
// the original record.
type Revocation struct {
	SchemaVersion string `json:"schema_version"`
	ContextID     string `json:"context_id"`
	IssuerID      string `json:"issuer_id"`
	RevokedAt     string `json:"revoked_at"`
	SigningSchema string `json:"signing_schema"`
	Signature     string `json:"signature"`
}

// Violation is a SEC validation failure with a stable reason code.
type Violation struct{ Code string }

func (v *Violation) Error() string { return v.Code }

func invalid(code string) error {
	if code == "" {
		code = "skill_context_invalid"
	}
	return &Violation{Code: code}
}

var (
	contextIDPattern = regexp.MustCompile(`^sec-[0-9a-f]{32}$`)
	instancePattern  = regexp.MustCompile(`^hi-[0-9a-f]{32}$`)
	agentPattern     = regexp.MustCompile(`^hri-[0-9a-f]{32}$`)
	skillIDPattern   = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$`)
	versionPattern   = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)
	hex64Pattern     = regexp.MustCompile(`^[0-9a-f]{64}$`)
	hex128Pattern    = regexp.MustCompile(`^[0-9a-f]{128}$`)
)

func textValid(s string, max int) bool {
	return s != "" && len(s) <= max
}

// Validate enforces the contract shape. Signature verification is separate
// (Store.verifyWithKey) so shape checks also run on unsigned candidates.
func (c *Context) Validate() error {
	if c.SchemaVersion != Schema || !contextIDPattern.MatchString(c.ContextID) || c.IssuerID != Issuer {
		return invalid("")
	}
	if c.SigningSchema != "" && c.SigningSchema != signing.SchemaLocalCanonicalV1 {
		return invalid("")
	}
	if !textValid(c.Subject.Platform, 64) || !instancePattern.MatchString(c.Subject.InstanceID) ||
		!agentPattern.MatchString(c.Subject.AgentID) || !textValid(c.Subject.SessionID, 256) {
		return invalid("")
	}
	if c.EvidenceLevel != EvidenceTask && c.EvidenceLevel != EvidenceSession {
		return invalid("")
	}
	if c.EvidenceLevel == EvidenceTask && !textValid(c.Subject.TaskID, 256) {
		return invalid("")
	}
	if c.Subject.TaskID != "" && len(c.Subject.TaskID) > 256 {
		return invalid("")
	}
	if !skillIDPattern.MatchString(c.Skill.SkillID) || !hex64Pattern.MatchString(c.Skill.ContentHash) {
		return invalid("")
	}
	if c.Skill.Version != "" && !versionPattern.MatchString(c.Skill.Version) {
		return invalid("")
	}
	if !textValid(c.Install.InstallID, 128) || !hex128Pattern.MatchString(c.Install.ClaimSignature) {
		return invalid("")
	}
	if !textValid(c.Authority.GrantID, 128) || !hex64Pattern.MatchString(c.Authority.GrantDigest) {
		return invalid("")
	}
	issued, err := time.Parse(time.RFC3339Nano, c.IssuedAt)
	if err != nil {
		return invalid("")
	}
	expires, err := time.Parse(time.RFC3339Nano, c.ExpiresAt)
	if err != nil || !issued.Before(expires) || expires.Sub(issued) > MaxTTL {
		return invalid("")
	}
	return nil
}

// Unsigned returns the canonical signing payload (everything but signature).
func (c *Context) Unsigned() map[string]any {
	b, _ := json.Marshal(c)
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	delete(m, "signature")
	return m
}

// Validate enforces the revocation contract shape.
func (r *Revocation) Validate() error {
	if r.SchemaVersion != RevocationSchema || !contextIDPattern.MatchString(r.ContextID) || r.IssuerID != Issuer {
		return invalid("")
	}
	if r.SigningSchema != "" && r.SigningSchema != signing.SchemaLocalCanonicalV1 {
		return invalid("")
	}
	if _, err := time.Parse(time.RFC3339Nano, r.RevokedAt); err != nil {
		return invalid("")
	}
	return nil
}

// Unsigned returns the canonical signing payload of the revocation.
func (r *Revocation) Unsigned() map[string]any {
	b, _ := json.Marshal(r)
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	delete(m, "signature")
	return m
}

// CallBinding delegates to trustedcontext.CallBinding so receipts and SEC
// verification share one canonical construction.
func CallBinding(platform, sessionID, agentID, taskID, tool, toolCallID string, params map[string]any) (string, error) {
	return trustedcontext.CallBinding(platform, sessionID, agentID, taskID, tool, toolCallID, params)
}
