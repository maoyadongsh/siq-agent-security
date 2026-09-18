package state

import (
	"encoding/json"
	"errors"
	"strings"
)

var ErrGrantProfileActivation = errors.New("state: grant profile activation requires the versioned compatibility barrier")

// Versioned Grant components are not a state-format activation route. Until
// that route and its recovery protocol are implemented, no public writer may
// leave a new interpretation in a directory readable by an older consumer.
func checkGrantProfileWrite(raw []byte) error {
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return ErrGrantProfileActivation
	}
	for _, name := range []string{"schema_version", "filesystem_profile", "filesystem_bindings"} {
		for field := range fields {
			if strings.EqualFold(field, name) {
				return ErrGrantProfileActivation
			}
		}
	}
	return nil
}
