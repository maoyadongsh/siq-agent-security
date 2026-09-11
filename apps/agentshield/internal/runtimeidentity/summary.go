package runtimeidentity

import (
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/intent"
	"sort"
)

// Summary deliberately excludes credential hashes, plaintext, and signatures.
// Issuance is not evidence that a runtime hook has been installed or verified.
type Summary struct {
	IdentityID        string                `json:"identity_id"`
	InstanceID        string                `json:"instance_id"`
	AgentID           string                `json:"agent_id"`
	Platform          string                `json:"platform"`
	GrantRef          intent.GrantReference `json:"grant_ref"`
	ActorID           string                `json:"actor_id"`
	CreatedAt         string                `json:"created_at"`
	SessionTTLSeconds int                   `json:"session_ttl_seconds"`
	Status            string                `json:"status"`
	RuntimeState      string                `json:"runtime_state"`
}

func (s *Store) summarize(r Record) (Summary, error) {
	revoked, err := s.revoked(r)
	if err != nil {
		return Summary{}, err
	}
	status := "issued"
	if revoked {
		status = "revoked"
	} else if _, err = s.intents.GrantForReference(r.GrantRef, r.Platform, r.AgentID); err != nil {
		status = "grant_unavailable"
	}
	return Summary{r.IdentityID, r.InstanceID, r.AgentID, r.Platform, r.GrantRef, r.ActorID, r.CreatedAt, r.SessionTTLSeconds, status, "unverified"}, nil
}
func (s *Store) Summary(id string) (Summary, error) {
	writeMu.RLock()
	defer writeMu.RUnlock()
	r, err := s.read(id)
	if err != nil {
		return Summary{}, err
	}
	return s.summarize(r)
}
func (s *Store) List() ([]Summary, error) {
	writeMu.RLock()
	defer writeMu.RUnlock()
	ids, err := recordIDs(filepath.Join(s.dir, "runtime-identities"), maxIdentities)
	if err != nil {
		return nil, ErrUnavailable
	}
	sort.Strings(ids)
	items := make([]Summary, 0, len(ids))
	for _, id := range ids {
		r, e := s.read(id)
		if e != nil {
			return nil, e
		}
		item, e := s.summarize(r)
		if e != nil {
			return nil, e
		}
		items = append(items, item)
	}
	return items, nil
}
