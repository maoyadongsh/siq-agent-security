package runtimeidentity

import "siq-agent-security/apps/agentshield/internal/intent"

// SelfView is authenticated metadata, never a claim of runtime protection.
type SelfView struct {
	SchemaVersion     string                `json:"schema_version"`
	IdentityID        string                `json:"identity_id"`
	InstanceID        string                `json:"instance_id"`
	AgentID           string                `json:"agent_id"`
	Platform          string                `json:"platform"`
	GrantRef          intent.GrantReference `json:"grant_ref"`
	SessionTTLSeconds int                   `json:"session_ttl_seconds"`
	Status            string                `json:"status"`
	RuntimeState      string                `json:"runtime_state"`
}

func (s *Store) Self(token string) (SelfView, error) {
	writeMu.RLock()
	defer writeMu.RUnlock()
	r, err := s.authenticate(token)
	if err != nil {
		return SelfView{}, ErrCredential
	}
	if platform, err := s.resolve(r.InstanceID); err != nil || platform != r.Platform {
		return SelfView{}, ErrCredential
	}
	return SelfView{SchemaVersion: "local-runtime-identity-self/v1", IdentityID: r.IdentityID,
		InstanceID: r.InstanceID, AgentID: r.AgentID, Platform: r.Platform, GrantRef: r.GrantRef,
		SessionTTLSeconds: r.SessionTTLSeconds, Status: "active", RuntimeState: "unverified"}, nil
}

// RevokeSelf needs no management session. The authenticated credential chooses
// the only revocable identity; Grant loss cannot block cleanup. A retry returns
// the existing immutable revocation, preserving its original actor and time.
func (s *Store) RevokeSelf(token string) (Revocation, error) {
	writeMu.Lock()
	defer writeMu.Unlock()
	r, err := s.credentialRecord(token)
	if err != nil {
		return Revocation{}, ErrCredential
	}
	return s.revokeRecord(r, "runtime-self:"+r.IdentityID)
}
