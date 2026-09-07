package state

import (
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/signing"
)

// IntentAuthority opens the trusted, immutable Intent store under this state
// directory. The caller supplies the already-loaded local signing identity.
func (s *Store) IntentAuthority(key *signing.Key) (*intent.Store, error) {
	return intent.Open(s.Dir, key)
}
