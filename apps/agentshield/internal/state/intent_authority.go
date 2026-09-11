package state

import (
	"errors"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/importsource"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/signing"
)

// IntentAuthority opens the trusted, immutable Intent store under this state
// directory. The caller supplies the already-loaded local signing identity.
func (s *Store) IntentAuthority(key *signing.Key) (*intent.Store, error) {
	return intent.OpenWithInstalledGrantLookup(s.Dir, key, s.RuntimeGrantWithSeq)
}

// SetRuntimeGrantCheck installs the daemon's trusted content verifier. Absent
// verification means deny; client input cannot register this callback.
func (s *Store) SetRuntimeGrantCheck(check func(*grant.Grant) error) {
	s.runtimeGrantMu.Lock()
	defer s.runtimeGrantMu.Unlock()
	s.runtimeGrantCheck = check
}
func (s *Store) RuntimeGrantWithSeq(id string) (*grant.Grant, int, error) {
	g, revision, err := s.GetGrantWithSeq(id)
	if err != nil || g == nil {
		return g, revision, err
	}
	if importsource.Reserved(g.AdmissionID) {
		s.runtimeGrantMu.RLock()
		check := s.runtimeGrantCheck
		s.runtimeGrantMu.RUnlock()
		if check == nil || check(g) != nil {
			return nil, revision, errors.New("state: installed grant unavailable")
		}
	}
	return g, revision, nil
}
