package runtimeidentity

import "path/filepath"

// HistoricalSource returns only identifiers for retained content lookup. It
// must never be used as current execution authorization or a credential.
func (s *Store) HistoricalSource(platform, session, agent, task, intentID, digest string) (string, string, error) {
	writeMu.RLock()
	defer writeMu.RUnlock()
	b, err := s.intents.HistoricalBinding(platform, session, agent)
	if err != nil || b.Platform != platform || b.SessionID != session || b.AgentID != agent || b.TaskID != task || b.IntentID != intentID || b.IntentDigest != digest {
		return "", "", ErrUnavailable
	}
	c, err := s.intents.Get(intentID)
	if err != nil || c.Digest != digest || c.TaskID != task || c.Agent.Platform != platform || c.Agent.ID != agent || b.AuthorityRevision != c.Authority.Revision {
		return "", "", ErrUnavailable
	}
	ids, err := recordIDs(filepath.Join(s.dir, "runtime-identities"), maxIdentities)
	if err != nil {
		return "", "", ErrUnavailable
	}
	matched := ""
	for _, id := range ids {
		r, err := s.read(id)
		if err != nil {
			return "", "", ErrUnavailable
		}
		if r.Platform == platform && r.AgentID == agent && bindingMatches(r, session, &c, &b) {
			if matched != "" {
				return "", "", ErrUnavailable
			}
			matched = r.IdentityID
		}
	}
	if matched == "" {
		return "", "", ErrUnavailable
	}
	return matched, b.BindingID, nil
}
