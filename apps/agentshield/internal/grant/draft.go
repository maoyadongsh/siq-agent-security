package grant

import (
	"encoding/json"
	"errors"
	"regexp"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
)

var ErrDraftSource = errors.New("grant_draft_source_invalid")
var draftIdentifier = regexp.MustCompile(`^grt-d-[a-f0-9]{64}$`)

// DraftFrom copies an exact signed permission template, never its approval or
// effective status. Expiration is deliberately retained, even when already past.
func DraftFrom(source Grant, policy DesiredPolicy, id string, now time.Time, key *signing.Key) (*Result, error) {
	if key == nil || !Verify(key.Public(), source) || !draftIdentifier.MatchString(id) || source.DefaultEffect != "deny" || source.DesiredPolicyRef == nil {
		return nil, ErrDraftSource
	}
	switch source.Status {
	case "approved", "deployed", "effective", "revoked":
	default:
		return nil, ErrDraftSource
	}
	if source.ExpiresAt != nil {
		if _, err := time.Parse(time.RFC3339Nano, *source.ExpiresAt); err != nil {
			return nil, ErrDraftSource
		}
	}
	// JSON cloning also detaches nested conditions, platform lists and policy maps.
	raw, err := json.Marshal(Result{Grant: source, DesiredPolicy: policy})
	if err != nil {
		return nil, ErrDraftSource
	}
	var out Result
	if json.Unmarshal(raw, &out) != nil {
		return nil, ErrDraftSource
	}
	dp := out.DesiredPolicy
	version, ok := dp["version"].(float64)
	if !ok || version != float64(source.DesiredPolicyRef.Version) || dp["policy_id"] != source.DesiredPolicyRef.PolicyID {
		return nil, ErrDraftSource
	}
	g := &out.Grant
	g.GrantID = id
	g.Status = "pending_approval"
	g.ApprovedBy = nil
	g.EffectiveReadback = nil
	g.CreatedAt = now.UTC().Format(time.RFC3339Nano)
	g.DesiredPolicyRef.PolicyID = "pol-" + id
	g.DesiredPolicyRef.Version = 1
	dp["policy_id"] = g.DesiredPolicyRef.PolicyID
	dp["version"] = 1
	dp["status"] = "validated"
	for i := range g.Facts {
		f := &g.Facts[i]
		if f.State == "effective" {
			f.State = "declared"
		} else if f.State != "declared" && f.State != "inferred" {
			f.State = "inferred"
		}
		if len(f.EvidenceIDs) == 0 {
			f.EvidenceIDs = []string{"source_grant:" + source.GrantID}
		}
		f.Authority = "agentshield"
		f.AuthorityRevision = nil
		f.ReadbackEvidenceID = nil
	}
	resign(key, g)
	if g.Signature == "" {
		return nil, ErrDraftSource
	}
	return &out, nil
}
