package skillcontext

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

const NativeSessionSchema = "native-skill-managed-session/v1"
const NativeCallSchema = "native-skill-call/v1"
const NativeCallMaxTTL = 5 * time.Minute

type nativeSigned struct {
	SchemaVersion  string       `json:"schema_version"`
	IssuerID       string       `json:"issuer_id"`
	Subject        Subject      `json:"subject"`
	AgentAuthority AuthorityRef `json:"agent_authority"`
	IssuedAt       string       `json:"issued_at"`
	ExpiresAt      string       `json:"expires_at"`
	SigningSchema  string       `json:"signing_schema"`
	Signature      string       `json:"signature"`
}

type NativeSession struct {
	nativeSigned
	RegistrationID        string `json:"registration_id"`
	RuntimeArtifactSHA256 string `json:"runtime_artifact_sha256"`
}

type NativeSessionRef struct {
	RegistrationID string `json:"registration_id"`
	Signature      string `json:"signature"`
}

// NativeCall contains no raw tool parameters and grants no execution right.
type NativeCall struct {
	nativeSigned
	CallID         string           `json:"call_id"`
	SessionRef     NativeSessionRef `json:"session_ref"`
	Tool           string           `json:"tool"`
	ToolCallID     string           `json:"tool_call_id"`
	RequestBinding string           `json:"request_binding"`
	NoSkill        bool             `json:"no_skill"`
	Context        *ParentRef       `json:"context,omitempty"`
}

func nativeUnsigned(doc any) map[string]any {
	b, _ := json.Marshal(doc)
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	delete(m, "signature")
	return m
}

func nativeID(prefix string, fields map[string]any) string {
	b, _ := canon.Marshal(fields)
	h := sha256.Sum256(b)
	return prefix + hex.EncodeToString(h[:16])
}

func nativeSubject(s Subject) map[string]any {
	b, _ := json.Marshal(s)
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	return m
}

func sessionSubject(s Subject) Subject { s.TaskID = ""; return s }
func nativeSessionID(s Subject) string {
	return nativeID("nsess-", map[string]any{"domain": NativeSessionSchema, "subject": nativeSubject(sessionSubject(s))})
}
func nativeCallID(s Subject, callID string) string {
	return nativeID("ncall-", map[string]any{"domain": NativeCallSchema, "subject": nativeSubject(s), "tool_call_id": callID})
}

func validNativeSubject(s Subject, task bool) bool {
	return textValid(s.Platform, 64) && instancePattern.MatchString(s.InstanceID) &&
		s.AgentID == "hri-"+strings.TrimPrefix(s.InstanceID, "hi-") && textValid(s.SessionID, 256) &&
		((task && textValid(s.TaskID, 256)) || (!task && s.TaskID == ""))
}

func (c nativeSigned) valid(schema string, task bool, maxTTL time.Duration) bool {
	issued, e1 := time.Parse(time.RFC3339Nano, c.IssuedAt)
	expires, e2 := time.Parse(time.RFC3339Nano, c.ExpiresAt)
	return c.SchemaVersion == schema && c.IssuerID == Issuer && c.SigningSchema == signing.SchemaLocalCanonicalV1 &&
		validNativeSubject(c.Subject, task) && textValid(c.AgentAuthority.GrantID, 128) && hex64Pattern.MatchString(c.AgentAuthority.GrantDigest) &&
		e1 == nil && e2 == nil && issued.Before(expires) && expires.Sub(issued) <= maxTTL
}

func (s NativeSession) Validate() error {
	if !s.nativeSigned.valid(NativeSessionSchema, false, MaxTTL) || s.RegistrationID != nativeSessionID(s.Subject) ||
		!hex64Pattern.MatchString(s.RuntimeArtifactSHA256) {
		return invalid("native_skill_session_invalid")
	}
	return nil
}
func (c NativeCall) Validate() error {
	if !c.nativeSigned.valid(NativeCallSchema, true, NativeCallMaxTTL) || c.CallID != nativeCallID(c.Subject, c.ToolCallID) ||
		c.SessionRef.RegistrationID != nativeSessionID(c.Subject) || !hex128Pattern.MatchString(c.SessionRef.Signature) ||
		!textValid(c.Tool, 128) || !textValid(c.ToolCallID, 256) || !hex64Pattern.MatchString(c.RequestBinding) ||
		c.NoSkill != (c.Context == nil) {
		return invalid("native_skill_call_invalid")
	}
	if c.Context != nil && (!contextIDPattern.MatchString(c.Context.ContextID) || !hex128Pattern.MatchString(c.Context.Signature)) {
		return invalid("native_skill_call_invalid")
	}
	return nil
}

func nativeCurrent(c nativeSigned, now time.Time, until time.Time) bool {
	issued, e1 := time.Parse(time.RFC3339Nano, c.IssuedAt)
	expires, e2 := time.Parse(time.RFC3339Nano, c.ExpiresAt)
	return e1 == nil && e2 == nil && !now.Before(issued) && now.Before(expires) && !expires.After(until)
}
