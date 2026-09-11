package intent

import (
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/importsource"
)

// GrantLookup must return only committed state; the Intent store verifies its
// signature and identity before using it as selected authority.
type GrantLookup func(id string) (*grant.Grant, int, error)

type GrantReference struct {
	GrantID          string `json:"grant_id"`
	AdmissionID      string `json:"admission_id"`
	PermissionDigest string `json:"permission_digest"`
}

// SelectGrant validates committed authority before an instance credential is
// issued. Callers must retain the returned reference and revalidate it later.
func (s *Store) SelectGrant(id, platform, agent string, expectedRevision int) (GrantReference, error) {
	g, revision, err := s.selectedGrant(id, platform, agent)
	if err != nil {
		return GrantReference{}, err
	}
	if expectedRevision < 0 || expectedRevision != revision {
		return GrantReference{}, violation("intent_grant_revision_conflict")
	}
	digest, err := grant.PermissionDigest(*g)
	if err != nil {
		return GrantReference{}, violation("intent_invalid_grant_selection")
	}
	return GrantReference{GrantID: g.GrantID, AdmissionID: g.AdmissionID, PermissionDigest: digest}, nil
}

// GrantForReference never substitutes a newer or broader grant.
func (s *Store) GrantForReference(ref GrantReference, platform, agent string) (*grant.Grant, error) {
	return s.resolveGrantSelection(Binding{GrantRef: &ref, Platform: platform, AgentID: agent})
}

func (s *Store) selectedGrant(id, platform, agent string) (*grant.Grant, int, error) {
	if s.grants == nil {
		return nil, 0, violation("intent_grant_resolver_unavailable")
	}
	g, revision, err := s.grants(id)
	if err != nil || g == nil {
		return nil, 0, violation("intent_grant_unavailable")
	}
	if g.GrantID != id || !grant.Verify(s.key.Public(), *g) {
		return nil, 0, violation("intent_grant_signature_invalid")
	}
	if g.Platform != platform || g.Subject.ID != agent || g.Subject.Type != "agent_instance" {
		return nil, 0, violation("intent_grant_subject_mismatch")
	}
	// Imported approved documents are selectable only through a lookup that
	// verifies the separately committed installation binding (state.RuntimeGrantWithSeq).
	if g.Status != "deployed" && g.Status != "effective" && !(s.installedGrantLookup && g.Status == "approved" && importsource.Reserved(g.AdmissionID)) {
		return nil, 0, violation("intent_grant_inactive")
	}
	if grant.ValidateLifetime(*g, time.Now()) != nil {
		return nil, 0, violation("intent_grant_expired")
	}
	return g, revision, nil
}

func (s *Store) resolveGrantSelection(b Binding) (*grant.Grant, error) {
	if b.GrantRef == nil {
		return nil, nil
	}
	g, _, err := s.selectedGrant(b.GrantRef.GrantID, b.Platform, b.AgentID)
	if err != nil {
		return nil, err
	}
	digest, err := grant.PermissionDigest(*g)
	if err != nil || b.GrantRef.AdmissionID != g.AdmissionID || b.GrantRef.PermissionDigest != digest {
		return nil, violation("intent_grant_digest_mismatch")
	}
	return g, nil
}

// BindWithGrant derives all reference fields from an exact preview revision.
// A concurrent later mutation is caught again on every runtime resolution.
func (s *Store) BindWithGrant(b Binding, grantID string, expectedRevision int) (Binding, error) {
	if b.GrantRef != nil || expectedRevision < 0 {
		return b, violation("intent_invalid_grant_selection")
	}
	g, revision, err := s.selectedGrant(grantID, b.Platform, b.AgentID)
	if err != nil {
		return b, err
	}
	if revision != expectedRevision {
		return b, violation("intent_grant_revision_conflict")
	}
	digest, err := grant.PermissionDigest(*g)
	if err != nil {
		return b, violation("intent_invalid_grant_selection")
	}
	b.GrantRef = &GrantReference{GrantID: g.GrantID, AdmissionID: g.AdmissionID, PermissionDigest: digest}
	return s.bindSelected(b, g)
}

// BindWithReference retains an already-confirmed permission digest even when
// ordinary readback updates the storage revision. Changed permissions fail closed.
func (s *Store) BindWithReference(b Binding, ref GrantReference) (Binding, error) {
	if b.GrantRef != nil {
		return b, violation("intent_invalid_grant_selection")
	}
	g, err := s.GrantForReference(ref, b.Platform, b.AgentID)
	if err != nil {
		return b, err
	}
	b.GrantRef = &ref
	return s.bindSelected(b, g)
}

func (s *Store) bindSelected(b Binding, g *grant.Grant) (Binding, error) {
	if g.ExpiresAt != nil {
		end, _ := time.Parse(time.RFC3339Nano, *g.ExpiresAt)
		if b.ExpiresAt == "" {
			b.ExpiresAt = *g.ExpiresAt
		} else {
			requested, e := time.Parse(time.RFC3339Nano, b.ExpiresAt)
			if e != nil {
				return b, violation("intent_invalid_time_window")
			}
			if requested.After(end) {
				b.ExpiresAt = *g.ExpiresAt
			}
		}
	}
	// Clamp to Intent too; legacy Bind keeps its original reject-long-window semantics.
	c, err := s.Get(b.IntentID)
	if err != nil {
		return b, err
	}
	if b.ExpiresAt != "" {
		selectedEnd, e := time.Parse(time.RFC3339Nano, b.ExpiresAt)
		intentEnd, e2 := time.Parse(time.RFC3339Nano, c.ExpiresAt)
		if e != nil || e2 != nil {
			return b, violation("intent_invalid_time_window")
		}
		if selectedEnd.After(intentEnd) {
			b.ExpiresAt = c.ExpiresAt
		}
	}
	return s.bind(b)
}
