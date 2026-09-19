package state

import (
	"encoding/json"
	"errors"
	"strings"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

var ErrGrantProfileActivation = errors.New("state: grant profile activation requires the versioned compatibility barrier")

// A versioned Grant never activates its own interpretation. Its state root must
// already have a completed, independently confirmed compatibility transition.
func checkGrantProfileWrite(dir string, raw []byte) error {
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return ErrGrantProfileActivation
	}
	extended := false
	for _, name := range []string{"schema_version", "filesystem_profile", "filesystem_bindings"} {
		for field := range fields {
			if strings.EqualFold(field, name) {
				extended = true
			}
		}
	}
	if extended {
		var g grant.Grant
		if json.Unmarshal(raw, &g) != nil || g.SchemaVersion != "grant/v2" || grant.ValidateFilesystemProfile(g) != nil {
			return ErrGrantProfileActivation
		}
		if err := stateformat.RequireWindowsProfile(dir); err != nil {
			return errors.Join(ErrGrantProfileActivation, err)
		}
	}
	return nil
}
