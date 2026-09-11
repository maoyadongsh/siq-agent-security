package state

import (
	"encoding/json"
	"errors"
	"fmt"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/grant"
)

// GrantPolicy reads only the policy version named by the signed Grant. It does
// not choose a newer policy or accept a path supplied by an HTTP client.
func (s *Store) GrantPolicy(g grant.Grant) (grant.DesiredPolicy, error) {
	ref := g.DesiredPolicyRef
	if ref == nil || !safeID(ref.PolicyID) || ref.Version < 1 {
		return nil, errors.New("state: invalid policy reference")
	}
	raw, err := readCommitFile(filepath.Join(s.Dir, "policies", fmt.Sprintf("%s.v%d.json", ref.PolicyID, ref.Version)))
	if err != nil {
		return nil, err
	}
	var policy grant.DesiredPolicy
	if json.Unmarshal(raw, &policy) != nil || policy == nil || policy["policy_id"] != ref.PolicyID || policy["version"] != float64(ref.Version) {
		return nil, errors.New("state: policy reference mismatch")
	}
	return policy, nil
}
