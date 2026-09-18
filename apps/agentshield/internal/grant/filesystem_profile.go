package grant

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"errors"
	"reflect"
	"strings"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/runtimepath"
	"siq-agent-security/apps/agentshield/internal/signing"
)

var ErrFilesystemProfile = errors.New("grant_filesystem_profile_invalid")

// Legacy documents cannot smuggle new interpretation fields as empty/null
// values that would disappear again when their signatures are reconstructed.
func (g *Grant) UnmarshalJSON(raw []byte) error {
	type wire Grant
	var value wire
	if err := json.Unmarshal(raw, &value); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return ErrFilesystemProfile
	}
	extended := false
	for field := range fields {
		for _, name := range []string{"schema_version", "filesystem_profile", "filesystem_bindings"} {
			if strings.EqualFold(field, name) {
				if field != name {
					return ErrFilesystemProfile
				}
				extended = true
			}
		}
	}
	if extended {
		if value.SchemaVersion != "grant/v2" {
			return ErrFilesystemProfile
		}
		known := map[string]bool{}
		shape := reflect.TypeOf(value)
		for i := 0; i < shape.NumField(); i++ {
			known[strings.Split(shape.Field(i).Tag.Get("json"), ",")[0]] = true
		}
		for field := range fields {
			if !known[field] {
				return ErrFilesystemProfile
			}
		}
		decoder := json.NewDecoder(bytes.NewReader(raw))
		decoder.DisallowUnknownFields()
		if decoder.Decode(&value) != nil {
			return ErrFilesystemProfile
		}
		decoder = json.NewDecoder(bytes.NewReader(raw))
		token, err := decoder.Token()
		if err != nil || token != json.Delim('{') {
			return ErrFilesystemProfile
		}
		seen := map[string]bool{}
		for decoder.More() {
			token, err = decoder.Token()
			name, ok := token.(string)
			if err != nil || !ok || seen[name] {
				return ErrFilesystemProfile
			}
			seen[name] = true
			var v json.RawMessage
			if decoder.Decode(&v) != nil {
				return ErrFilesystemProfile
			}
		}
		if err := ValidateFilesystemProfile(Grant(value)); err != nil {
			return err
		}
	}
	*g = Grant(value)
	return nil
}

// ValidateFilesystemProfile checks signed shape, not current file availability.
// Revocation and historical signature verification must survive deleted scopes.
func ValidateFilesystemProfile(g Grant) error {
	if g.SchemaVersion == "" && g.FilesystemProfile == "" && g.FilesystemBindings == nil {
		return nil
	}
	if g.SchemaVersion != "grant/v2" || g.FilesystemProfile != string(runtimeaction.FilesystemWindowsLocalDriveV1) || g.FilesystemBindings == nil || g.Subject.Type != "agent_instance" || (g.Platform != "hermes" && g.Platform != "openclaw") || g.Skill != nil {
		return ErrFilesystemProfile
	}
	expected := map[string]bool{}
	seen := map[string]bool{}
	for _, f := range g.Facts {
		if f.FactID == "" || seen[f.FactID] {
			return ErrFilesystemProfile
		}
		seen[f.FactID] = true
		if f.Domain != "filesystem" {
			continue
		}
		if f.FactID == "" || expected[f.FactID] || f.Resource.Type != "path" || (f.Action != "fs.read" && f.Action != "fs.write") || (f.Effect != "allow" && f.Effect != "deny") {
			return ErrFilesystemProfile
		}
		if f.Resource.Value == "*" && f.Effect == "deny" {
			continue
		}
		canonical, err := runtimeaction.NormalizeResourceForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, "filesystem", f.Resource.Value)
		if err != nil || canonical != f.Resource.Value {
			return ErrFilesystemProfile
		}
		expected[f.FactID] = true
		digest, ok := (*g.FilesystemBindings)[f.FactID]
		raw, err := hex.DecodeString(digest)
		if !ok || err != nil || len(raw) != 32 || hex.EncodeToString(raw) != digest {
			return ErrFilesystemProfile
		}
	}
	if len(expected) != len(*g.FilesystemBindings) || len(expected) > 128 {
		return ErrFilesystemProfile
	}
	return nil
}

func bindFilesystemResources(g *Grant) error {
	if g.SchemaVersion != "grant/v2" || g.FilesystemProfile != string(runtimeaction.FilesystemWindowsLocalDriveV1) {
		return ErrFilesystemProfile
	}
	bindings := map[string]string{}
	for _, f := range g.Facts {
		if f.Domain != "filesystem" || f.Resource.Value == "*" && f.Effect == "deny" {
			continue
		}
		if _, exists := bindings[f.FactID]; exists {
			return ErrFilesystemProfile
		}
		if len(bindings) >= 128 {
			return ErrFilesystemProfile
		}
		snapshot, err := runtimepath.InspectWindows(f.Resource.Value, false)
		if err != nil {
			return ErrFilesystemProfile
		}
		digest, err := snapshot.IdentityDigest()
		if err != nil {
			return ErrFilesystemProfile
		}
		bindings[f.FactID] = digest
	}
	g.FilesystemBindings = &bindings
	return ValidateFilesystemProfile(*g)
}

// RecheckFilesystemBindings is required at approval and every exercise of a
// Windows grant. It must never silently update the approved identity digests.
func RecheckFilesystemBindings(g Grant) error {
	if err := ValidateFilesystemProfile(g); err != nil {
		return err
	}
	if g.SchemaVersion == "" {
		return nil
	}
	copy := g
	if err := bindFilesystemResources(&copy); err != nil {
		return err
	}
	for id, wanted := range *g.FilesystemBindings {
		if (*copy.FilesystemBindings)[id] != wanted {
			return ErrFilesystemProfile
		}
	}
	return nil
}

// PrepareWindowsResources produces a pending revision only. Callers must use
// the versioned human confirmation route and the state compatibility barrier
// before publication; this function neither persists nor approves anything.
func PrepareWindowsResources(source Grant, input ResourceEdit, confirm bool, key *signing.Key) (Grant, DesiredPolicy, error) {
	if !confirm || key == nil || !Verify(key.Public(), source) || source.Status != "pending_approval" || source.SchemaVersion != "" || source.Skill != nil || source.Subject.Type != "agent_instance" || (source.Platform != "hermes" && source.Platform != "openclaw") {
		return source, nil, ErrFilesystemProfile
	}
	raw, err := json.Marshal(source)
	if err != nil {
		return source, nil, ErrFilesystemProfile
	}
	var candidate Grant
	if json.Unmarshal(raw, &candidate) != nil {
		return source, nil, ErrFilesystemProfile
	}
	candidate.SchemaVersion = "grant/v2"
	candidate.FilesystemProfile = string(runtimeaction.FilesystemWindowsLocalDriveV1)
	return editResources(candidate, input, key)
}
