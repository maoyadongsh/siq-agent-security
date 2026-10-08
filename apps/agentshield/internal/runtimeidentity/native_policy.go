package runtimeidentity

import (
	"encoding/json"
	"path/filepath"
	"strings"
)

// NativeSkillPolicy is mandatory authority selection, not an attestation that
// the host is installed or running. Only the management enrollment supplies it.
type NativeSkillPolicy struct {
	Mode                  string `json:"mode"`
	RuntimeArtifactSHA256 string `json:"runtime_artifact_sha256"`
}

func validNativePolicy(p *NativeSkillPolicy) bool {
	return p != nil && p.Mode == "required" && hexDigest.MatchString(p.RuntimeArtifactSHA256)
}
func copyNativePolicy(p *NativeSkillPolicy) *NativeSkillPolicy {
	if p == nil {
		return nil
	}
	copy := *p
	return &copy
}
func sameNativePolicy(a, b *NativeSkillPolicy) bool {
	return a == nil && b == nil || a != nil && b != nil && *a == *b
}
func posixIdentity(r Record) bool {
	return r.SchemaVersion == "local-runtime-identity/v1" || r.SchemaVersion == "local-runtime-identity/v3" || r.SchemaVersion == "local-runtime-identity/v4" || r.SchemaVersion == "local-runtime-identity/v5"
}
func requestParent(r Record) bool {
	return r.RequestScope == nil && r.Platform == "hermes" && (r.SchemaVersion == "local-runtime-identity/v1" || r.SchemaVersion == "local-runtime-identity/v4")
}

func (p *NativeSkillPolicy) UnmarshalJSON(raw []byte) error {
	type wire NativeSkillPolicy
	var value wire
	var fields map[string]json.RawMessage
	if !uniqueJSONKeys(raw) || json.Unmarshal(raw, &fields) != nil || len(fields) != 2 || fields["mode"] == nil || fields["runtime_artifact_sha256"] == nil || json.Unmarshal(raw, &value) != nil || !validNativePolicy((*NativeSkillPolicy)(&value)) {
		return ErrInvalid
	}
	*p = NativeSkillPolicy(value)
	return nil
}

// NativePolicy reads mandatory mode from the signed root identity. No call,
// session or SEC record is consulted. Missing managed identity is an error,
// never evidence that native protection is optional. Session authentication
// remains a separate, mandatory check for the eventual tool request.
func (s *Store) NativePolicy(platform, agent string) (*NativeSkillPolicy, error) {
	if !strings.HasPrefix(agent, "hri-") {
		return nil, nil
	}
	instance := "hi-" + strings.TrimPrefix(agent, "hri-")
	if !instanceID.MatchString(instance) || !supportedIdentityPlatforms[platform] {
		return nil, ErrInvalid
	}
	writeMu.RLock()
	defer writeMu.RUnlock()
	ids, err := recordIDs(filepath.Join(s.dir, "runtime-identities"), maxIdentities)
	if err != nil {
		return nil, ErrUnavailable
	}
	var root *Record
	for _, id := range ids {
		r, err := s.read(id)
		if err != nil {
			return nil, err
		}
		if r.RequestScope != nil || r.InstanceID != instance {
			continue
		}
		revoked, err := s.revoked(r)
		if err != nil {
			return nil, err
		}
		if revoked {
			continue
		}
		if root != nil || r.Platform != platform {
			return nil, ErrConflict
		}
		root = &r
	}
	if root == nil {
		return nil, ErrUnavailable
	}
	if resolved, err := s.resolve(root.InstanceID); err != nil || resolved != root.Platform {
		return nil, ErrUnavailable
	}
	g, err := s.intents.GrantForReference(root.GrantRef, platform, agent)
	if err != nil || !recordGrantProfileMatches(*root, g) || s.checkRecordProfile(*root) != nil {
		return nil, ErrUnavailable
	}
	return copyNativePolicy(root.NativeSkillPolicy), nil
}
