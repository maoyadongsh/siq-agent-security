// Package effectevidence verifies signed effect records. A valid signature is
// not observer authorization and does not, by itself, establish completion.
package effectevidence

import (
	"bytes"
	"crypto/ed25519"
	"encoding/json"
	"errors"
	"io"
	"regexp"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/signing"
)

type Source struct {
	Type         string `json:"type"`
	SourceID     string `json:"source_id"`
	Independence string `json:"independence"`
}

type Evidence struct {
	SchemaVersion     string `json:"schema_version"`
	EvidenceID        string `json:"effect_evidence_id"`
	ActionID          string `json:"action_id"`
	DecisionReceiptID string `json:"decision_receipt_id"`
	EffectType        string `json:"effect_type"`
	ResourceRef       string `json:"resource_ref"`
	ExecutionState    string `json:"execution_state"`
	Source            Source `json:"source"`
	Coverage          string `json:"coverage"`
	Result            string `json:"result"`
	EvidenceDigest    string `json:"evidence_digest"`
	ObservedAt        string `json:"observed_at"`
	SigningSchema     string `json:"signing_schema"`
	Signature         string `json:"signature"`
}

var (
	ErrInvalid       = errors.New("effect_evidence_invalid")
	ErrSignature     = errors.New("effect_evidence_signature_invalid")
	idPattern        = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)
	digestPattern    = regexp.MustCompile(`^[0-9a-f]{64}$`)
	signaturePattern = regexp.MustCompile(`^[0-9a-f]{128}$`)
	resourcePattern  = regexp.MustCompile(`^(filesystem|network|message):sha256:[0-9a-f]{64}$`)
	timePattern      = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$`)
)

func member(value string, allowed ...string) bool {
	for _, candidate := range allowed {
		if value == candidate {
			return true
		}
	}
	return false
}

// ResourceReference reuses the action normalizer's digest; it never hashes an
// independently normalized path or persists the underlying resource value.
func ResourceReference(ref runtimeaction.ResourceRef) (string, error) {
	value := ref.Domain + ":sha256:" + ref.Digest
	if !resourcePattern.MatchString(value) {
		return "", ErrInvalid
	}
	return value, nil
}

func (e Evidence) Validate(now time.Time) error {
	if e.SchemaVersion != "effect-evidence/v1" || e.SigningSchema != signing.SchemaLocalCanonicalV1 || !idPattern.MatchString(e.EvidenceID) || !digestPattern.MatchString(e.EvidenceDigest) || !resourcePattern.MatchString(e.ResourceRef) {
		return ErrInvalid
	}
	for _, field := range []struct {
		value string
		limit int
	}{{e.ActionID, 256}, {e.DecisionReceiptID, 256}, {e.EffectType, 128}, {e.Source.SourceID, 256}} {
		if strings.TrimSpace(field.value) == "" || len(field.value) > field.limit {
			return ErrInvalid
		}
	}
	if !member(e.ExecutionState, "requested", "started", "completed", "failed", "unknown") || !member(e.Source.Type, "tool_report", "host_observer", "openshell", "provider_audit", "test_oracle", "unknown") || !member(e.Source.Independence, "self_reported", "host_independent", "external_independent", "unknown") || !member(e.Coverage, "full", "partial", "unknown") || !member(e.Result, "expected", "unexpected", "conflicting", "unknown") {
		return ErrInvalid
	}
	if e.Source.Type == "tool_report" && (e.Source.Independence != "self_reported" || e.Coverage != "unknown" || e.Result != "unknown") {
		return ErrInvalid
	}
	if e.Source.Type == "unknown" && (e.Source.Independence != "unknown" || e.Coverage != "unknown" || e.Result != "unknown") {
		return ErrInvalid
	}
	observed, err := time.Parse(time.RFC3339Nano, e.ObservedAt)
	if err != nil || len(e.ObservedAt) > 64 || !timePattern.MatchString(e.ObservedAt) || observed.After(now) {
		return ErrInvalid
	}
	return nil
}

func (e Evidence) Unsigned() map[string]any {
	raw, _ := json.Marshal(e)
	var doc map[string]any
	_ = json.Unmarshal(raw, &doc)
	delete(doc, "signature")
	return doc
}

func (e Evidence) Verify(pub ed25519.PublicKey, now time.Time) error {
	if err := e.Validate(now); err != nil {
		return err
	}
	if !signaturePattern.MatchString(e.Signature) || !signing.VerifyCanonical(pub, e.Unsigned(), e.Signature) {
		return ErrSignature
	}
	return nil
}

// Decode handles a single bounded signed record. Call Verify after decoding.
func Decode(raw []byte) (Evidence, error) {
	var e Evidence
	if len(raw) > 64<<10 {
		return e, ErrInvalid
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(&e) != nil {
		return Evidence{}, ErrInvalid
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return Evidence{}, ErrInvalid
	}
	return e, nil
}
