package runtimeidentity

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"path/filepath"
	"reflect"
	"strings"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/runtimepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

// InstanceInfo comes from server-owned inventory, never request fields. Root is
// the discovered profile directory; accepting it does not attest hook loading.
type InstanceInfo struct{ Platform, Root string }
type ResolveInstanceInfo func(string) (InstanceInfo, error)

var ErrProfileState = errors.New("windows_profile_activation_required")

func OpenWithInstances(dir string, key *signing.Key, intents *intent.Store, resolve ResolveInstanceInfo) (*Store, error) {
	if resolve == nil {
		return nil, ErrInvalid
	}
	s, err := Open(dir, key, intents, func(id string) (string, error) {
		info, e := resolve(id)
		return info.Platform, e
	})
	if err != nil {
		return nil, err
	}
	s.resolveInstance = resolve
	return s, nil
}

func validCreateProfile(req CreateRequest) bool {
	return req.SchemaVersion == "local-runtime-identity-create/v1" && !req.ConfirmFilesystemProfile || req.SchemaVersion == "local-runtime-identity-create/v2" && req.ConfirmFilesystemProfile
}
func validRecordProfile(r Record) bool {
	switch r.SchemaVersion {
	case "local-runtime-identity/v1":
		return r.RequestScope == nil && r.Platform != "workbuddy" && r.FilesystemProfile == "" && r.GrantRef.PermissionDigestSchema == ""
	case "local-runtime-identity/v2":
		return r.RequestScope == nil && r.FilesystemProfile == string(runtimeaction.FilesystemWindowsLocalDriveV1) && r.GrantRef.PermissionDigestSchema == "grant-permissions/v2"
	case "local-runtime-identity/v3":
		return r.Platform == "hermes" && r.FilesystemProfile == "" && r.GrantRef.PermissionDigestSchema == "" && validRequestScope(r.RequestScope)
	}
	return false
}
func recordGrantProfileMatches(r Record, g *grant.Grant) bool {
	return g != nil && validRecordProfile(r) && ((r.SchemaVersion == "local-runtime-identity/v1" || r.SchemaVersion == "local-runtime-identity/v3") && g.SchemaVersion == "" || r.SchemaVersion == "local-runtime-identity/v2" && g.SchemaVersion == "grant/v2" && g.FilesystemProfile == r.FilesystemProfile)
}
func (s *Store) checkRecordProfile(r Record) error {
	if r.SchemaVersion == "local-runtime-identity/v2" {
		if err := stateformat.RequireWindowsProfile(s.dir); err != nil {
			return err
		}
		if r.Platform == "workbuddy" {
			if s.resolveInstance == nil {
				return ErrUnavailable
			}
			info, err := s.resolveInstance(r.InstanceID)
			if err != nil || info.Platform != r.Platform {
				return ErrUnavailable
			}
			if snapshot, err := runtimepath.InspectWindows(info.Root, false); err != nil || !snapshot.IsDirectory() {
				return ErrUnavailable
			}
		}
	}
	return nil
}
func (s *Store) creationProfile(req CreateRequest, platform string, g *grant.Grant) (string, error) {
	if req.SchemaVersion == "local-runtime-identity-create/v1" {
		if platform == "workbuddy" || g == nil || g.SchemaVersion != "" {
			return "", ErrInvalid
		}
		return "", nil
	}
	if stateformat.RequireWindowsProfile(s.dir) != nil {
		return "", ErrProfileState
	}
	if !req.ConfirmFilesystemProfile || g == nil || g.SchemaVersion != "grant/v2" || g.FilesystemProfile != string(runtimeaction.FilesystemWindowsLocalDriveV1) || s.resolveInstance == nil {
		return "", ErrUnavailable
	}
	info, err := s.resolveInstance(req.InstanceID)
	if err != nil || info.Platform != platform {
		return "", ErrUnavailable
	}
	if _, err := runtimepath.InspectWindows(info.Root, false); err != nil {
		return "", ErrUnavailable
	}
	if grant.RecheckFilesystemBindings(*g) != nil {
		return "", ErrUnavailable
	}
	return g.FilesystemProfile, nil
}

func (r *Record) UnmarshalJSON(raw []byte) error {
	type wire Record
	var value wire
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&value) != nil {
		return ErrInvalid
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return ErrInvalid
	}
	for name := range fields {
		if strings.EqualFold(name, "filesystem_profile") && (name != "filesystem_profile" || value.SchemaVersion != "local-runtime-identity/v2") {
			return ErrInvalid
		}
	}
	if !validRecordProfile(Record(value)) {
		return ErrInvalid
	}
	if (value.SchemaVersion == "local-runtime-identity/v2" || value.SchemaVersion == "local-runtime-identity/v3") && !exactRecordFields(raw, value.SchemaVersion) {
		return ErrInvalid
	}
	*r = Record(value)
	return nil
}

func exactRecordFields(raw []byte, version string) bool {
	required := map[string]bool{}
	typ := reflect.TypeOf(Record{})
	for i := 0; i < typ.NumField(); i++ {
		required[strings.Split(typ.Field(i).Tag.Get("json"), ",")[0]] = true
	}
	if version == "local-runtime-identity/v2" {
		delete(required, "request_scope")
	} else {
		delete(required, "filesystem_profile")
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	if first, err := d.Token(); err != nil || first != json.Delim('{') {
		return false
	}
	for d.More() {
		key, err := d.Token()
		name, ok := key.(string)
		if err != nil || !ok || !required[name] {
			return false
		}
		delete(required, name)
		var value json.RawMessage
		if d.Decode(&value) != nil || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return false
		}
	}
	if last, err := d.Token(); err != nil || last != json.Delim('}') || len(required) != 0 {
		return false
	}
	var extra any
	return d.Decode(&extra) == io.EOF
}

// VerifySessionAuthority revalidates signed instance authority for an observer
// without exposing or reading its credential. Revocation is checked now.
func (s *Store) VerifySessionAuthority(c intent.Contract, session string) error {
	writeMu.RLock()
	defer writeMu.RUnlock()
	if c.Authority.Issuer != "local-runtime-identity" || c.Validate() != nil {
		return ErrInvalid
	}
	ids, err := recordIDs(filepath.Join(s.dir, "runtime-identities"), maxIdentities)
	if err != nil {
		return ErrUnavailable
	}
	for _, id := range ids {
		r, err := s.read(id)
		if err != nil {
			return ErrUnavailable
		}
		if recordDigest(r) != c.Authority.Revision {
			continue
		}
		revoked, err := s.revoked(r)
		if err != nil || revoked || s.checkRecordProfile(r) != nil || s.checkRequestRecord(r) != nil || validateManagedSession(r, session) != nil {
			return ErrUnavailable
		}
		current, binding, err := s.intents.ResolveBinding(r.Platform, session, r.AgentID)
		if err != nil || current == nil || current.Digest != c.Digest || !bindingMatches(r, session, current, binding) {
			return ErrUnavailable
		}
		return nil
	}
	return ErrUnavailable
}
