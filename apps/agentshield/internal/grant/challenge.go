// Approval challenges bind high-impact grant approve to a single-use proof
// (DEV02-B): grant digest, subject, scope, expected revision, nonce, expiry.
package grant

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
)

const (
	// ChallengeTTL is how long an issued approve challenge remains valid.
	ChallengeTTL = 5 * time.Minute
)

// ApprovalChallenge is a single-use proof required for grant approve.
type ApprovalChallenge struct {
	ChallengeID      string  `json:"challenge_id"`
	GrantID          string  `json:"grant_id"`
	GrantDigest      string  `json:"grant_digest"`
	ExpectedRevision int     `json:"expected_revision"`
	SubjectType      string  `json:"subject_type"`
	SubjectID        string  `json:"subject_id"`
	Platform         string  `json:"platform"`
	ScopeDigest      string  `json:"scope_digest"`
	Nonce            string  `json:"nonce"`
	ExpiresAt        string  `json:"expires_at"`
	CreatedAt        string  `json:"created_at"`
	ConsumedAt       *string `json:"consumed_at,omitempty"`
}

// BindingDigest returns a stable hex SHA-256 over the grant fields that an
// approve decision must lock. Signature and approval metadata are excluded so
// the digest describes the pending authorization body.
func BindingDigest(g Grant) (string, error) {
	payload := map[string]any{
		"grant_id":                 g.GrantID,
		"admission_id":             g.AdmissionID,
		"subject":                  g.Subject,
		"platform":                 g.Platform,
		"facts":                    g.Facts,
		"default_effect":           g.DefaultEffect,
		"hermes_toolset_allowlist": g.HermesToolsetAllowlist,
		"openclaw_tool_policy":     g.OpenClawToolPolicy,
		"desired_policy_ref":       g.DesiredPolicyRef,
		"overlap_conflicts":        g.OverlapConflicts,
		"enforcement_mode":         g.EnforcementMode,
		"status":                   g.Status,
		"expires_at":               g.ExpiresAt,
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	v, err := canon.Decode(raw)
	if err != nil {
		return "", err
	}
	canonBytes, err := canon.Marshal(v)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(canonBytes)
	return hex.EncodeToString(sum[:]), nil
}

// ScopeDigest summarizes tools/resources the human is authorizing.
func ScopeDigest(g Grant) (string, error) {
	tools := map[string]struct{}{}
	resources := map[string]struct{}{}
	for _, f := range g.Facts {
		if f.Effect == "allow" || f.Effect == "require_approval" {
			key := f.Domain + ":" + f.Action
			tools[key] = struct{}{}
			resources[f.Domain+"|"+f.Resource.Type+"|"+f.Resource.Value] = struct{}{}
		}
	}
	if g.HermesToolsetAllowlist != nil {
		for _, t := range *g.HermesToolsetAllowlist {
			tools["hermes:"+t] = struct{}{}
		}
	}
	if g.OpenClawToolPolicy != nil {
		for _, t := range g.OpenClawToolPolicy.Allow {
			tools["openclaw:allow:"+t] = struct{}{}
		}
		for _, t := range g.OpenClawToolPolicy.RequireApproval {
			tools["openclaw:req:"+t] = struct{}{}
		}
	}
	payload := map[string]any{
		"tools":     sortedKeys(tools),
		"resources": sortedKeys(resources),
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	v, err := canon.Decode(raw)
	if err != nil {
		return "", err
	}
	canonBytes, err := canon.Marshal(v)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(canonBytes)
	return hex.EncodeToString(sum[:]), nil
}

func sortedKeys(m map[string]struct{}) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// IssueChallenge builds a fresh single-use challenge bound to g at revision.
func IssueChallenge(g Grant, expectedRevision int, now time.Time) (*ApprovalChallenge, error) {
	if g.Status != "pending_approval" {
		return nil, fmt.Errorf("grant: cannot challenge status %s (need pending_approval)", g.Status)
	}
	if now.IsZero() {
		now = time.Now().UTC()
	}
	digest, err := BindingDigest(g)
	if err != nil {
		return nil, err
	}
	scope, err := ScopeDigest(g)
	if err != nil {
		return nil, err
	}
	var idRaw, nonceRaw [16]byte
	if _, err := rand.Read(idRaw[:]); err != nil {
		return nil, err
	}
	if _, err := rand.Read(nonceRaw[:]); err != nil {
		return nil, err
	}
	return &ApprovalChallenge{
		ChallengeID:      "chl-" + hex.EncodeToString(idRaw[:]),
		GrantID:          g.GrantID,
		GrantDigest:      digest,
		ExpectedRevision: expectedRevision,
		SubjectType:      g.Subject.Type,
		SubjectID:        g.Subject.ID,
		Platform:         g.Platform,
		ScopeDigest:      scope,
		Nonce:            hex.EncodeToString(nonceRaw[:]),
		ExpiresAt:        now.Add(ChallengeTTL).Format(time.RFC3339),
		CreatedAt:        now.Format(time.RFC3339),
	}, nil
}

var (
	ErrChallengeMissing    = errors.New("grant: approval challenge required")
	ErrChallengeConsumed   = errors.New("grant: approval challenge already consumed")
	ErrChallengeExpired    = errors.New("grant: approval challenge expired")
	ErrChallengeMismatch   = errors.New("grant: approval challenge binding mismatch")
	ErrChallengeBadNonce   = errors.New("grant: approval challenge nonce mismatch")
	ErrChallengeWrongGrant = errors.New("grant: approval challenge grant_id mismatch")
)

// ValidateChallenge checks ch against the live grant and request without consuming.
func ValidateChallenge(ch ApprovalChallenge, g Grant, expectedRevision int, nonce string, now time.Time) error {
	if ch.ChallengeID == "" || nonce == "" {
		return ErrChallengeMissing
	}
	if ch.ConsumedAt != nil && *ch.ConsumedAt != "" {
		return ErrChallengeConsumed
	}
	if now.IsZero() {
		now = time.Now().UTC()
	}
	exp, err := time.Parse(time.RFC3339, ch.ExpiresAt)
	if err != nil || !now.Before(exp) {
		return ErrChallengeExpired
	}
	if ch.GrantID != g.GrantID {
		return ErrChallengeWrongGrant
	}
	if ch.ExpectedRevision != expectedRevision {
		return ErrChallengeMismatch
	}
	digest, err := BindingDigest(g)
	if err != nil {
		return err
	}
	if subtle.ConstantTimeCompare([]byte(ch.GrantDigest), []byte(digest)) != 1 {
		return ErrChallengeMismatch
	}
	scope, err := ScopeDigest(g)
	if err != nil {
		return err
	}
	if subtle.ConstantTimeCompare([]byte(ch.ScopeDigest), []byte(scope)) != 1 {
		return ErrChallengeMismatch
	}
	if ch.SubjectType != g.Subject.Type || ch.SubjectID != g.Subject.ID || ch.Platform != g.Platform {
		return ErrChallengeMismatch
	}
	if subtle.ConstantTimeCompare([]byte(ch.Nonce), []byte(nonce)) != 1 {
		return ErrChallengeBadNonce
	}
	return nil
}

// MarkConsumed returns a copy with ConsumedAt set.
func MarkConsumed(ch ApprovalChallenge, now time.Time) ApprovalChallenge {
	if now.IsZero() {
		now = time.Now().UTC()
	}
	ts := now.Format(time.RFC3339)
	ch.ConsumedAt = &ts
	return ch
}
