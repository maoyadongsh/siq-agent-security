package skillcontext

import (
	"crypto/ed25519"
	"encoding/json"
	"regexp"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
)

const InvocationSchema = "skill-execution-context/v2"
const EvidenceInvocation = "controlled_invocation"
const InvocationMaxTTL = time.Hour

var loadIDPattern = regexp.MustCompile(`^nload-[0-9a-f]{32}$`)

// NativeLoadRef records facts verified by the trusted loader integration.
// These hashes alone are not evidence that a caller owns the loader.
type NativeLoadRef struct {
	LoadID                string `json:"load_id"`
	SkillFileSHA256       string `json:"skill_file_sha256"`
	RuntimeArtifactSHA256 string `json:"runtime_artifact_sha256"`
}

// ParentRef pins an immutable ancestor, whose authority must also be checked.
type ParentRef struct {
	ContextID string `json:"context_id"`
	Signature string `json:"signature"`
}

// InvocationContext is the v2 signed document only. It is deliberately not
// accepted by Store's v1 issuer, reader or VerifyForEngine. Live issuance,
// per-call binding and the separate Agent/Skill authority intersection must
// be implemented before a v2 document can authorize an actual tool call.
type InvocationContext struct {
	Context
	AgentAuthority AuthorityRef  `json:"agent_authority"`
	Loader         NativeLoadRef `json:"loader"`
	Parent         *ParentRef    `json:"parent,omitempty"`
}

// Validate checks document shape, not installation or live authority.
func (c *InvocationContext) Validate() error {
	if c.SchemaVersion != InvocationSchema || c.EvidenceLevel != EvidenceInvocation ||
		c.SigningSchema != signing.SchemaLocalCanonicalV1 || !textValid(c.Subject.TaskID, 256) {
		return invalid("")
	}
	// Share v1 field constraints without changing either signed representation.
	base := c.Context
	base.SchemaVersion, base.EvidenceLevel = Schema, EvidenceTask
	if base.Validate() != nil || c.Subject.AgentID != "hri-"+strings.TrimPrefix(c.Subject.InstanceID, "hi-") {
		return invalid("")
	}
	if !textValid(c.AgentAuthority.GrantID, 128) || !hex64Pattern.MatchString(c.AgentAuthority.GrantDigest) ||
		c.AgentAuthority.GrantID == c.Authority.GrantID {
		return invalid("")
	}
	if !loadIDPattern.MatchString(c.Loader.LoadID) || !hex64Pattern.MatchString(c.Loader.SkillFileSHA256) ||
		!hex64Pattern.MatchString(c.Loader.RuntimeArtifactSHA256) {
		return invalid("")
	}
	if c.Parent != nil && (!contextIDPattern.MatchString(c.Parent.ContextID) ||
		!hex128Pattern.MatchString(c.Parent.Signature) || c.Parent.ContextID == c.ContextID) {
		return invalid("")
	}
	issued, _ := time.Parse(time.RFC3339Nano, c.IssuedAt)
	expires, _ := time.Parse(time.RFC3339Nano, c.ExpiresAt)
	if expires.Sub(issued) > InvocationMaxTTL {
		return invalid("")
	}
	return nil
}

func (c *InvocationContext) Unsigned() map[string]any {
	raw, _ := json.Marshal(c)
	var document map[string]any
	_ = json.Unmarshal(raw, &document)
	delete(document, "signature")
	return document
}

// VerifySignature authenticates every v2 field, including the separate Agent
// grant and loader/parent identities. It does NOT verify live dependencies,
// expiry relative to now, revocation, scope coverage or a tool call binding.
func (c *InvocationContext) VerifySignature(public ed25519.PublicKey) error {
	if c.Validate() != nil || signing.VerifyWithSchema(c.SigningSchema, public, c.Unsigned(), c.Signature) != nil {
		return invalid("")
	}
	return nil
}
