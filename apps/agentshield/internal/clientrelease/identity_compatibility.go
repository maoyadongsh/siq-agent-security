package clientrelease

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

// The signed identity can require native enforcement before the first native
// session exists. A pre-native candidate must not be staged for such a state.
// This is a bounded version check, not authentication or signature verification.
func checkLegacyIdentityCompatibility(dir string, snapshot *privatefs.ReadSnapshot) error {
	entries, err := eventEntries(filepath.Join(dir, "runtime-identities"), 512)
	if err != nil || len(entries) > 512 {
		return errEventCompatibility
	}
	for _, entry := range entries {
		name := filepath.Join("runtime-identities", entry.Name())
		path := filepath.Join(dir, name)
		before, err := os.Lstat(path)
		if err != nil || !before.Mode().IsRegular() || before.Size() > 16<<10 || (runtime.GOOS != "windows" && before.Mode().Perm()&0077 != 0) {
			return errEventCompatibility
		}
		raw, err := snapshot.ReadFile(name, 16<<10)
		if err != nil {
			return errEventCompatibility
		}
		after, err := os.Lstat(path)
		if err != nil || !os.SameFile(before, after) || before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) || !legacyIdentityRecord(raw) {
			return errEventCompatibility
		}
	}
	return nil
}

func legacyIdentityRecord(raw []byte) bool {
	var record runtimeidentity.Record
	if json.Unmarshal(raw, &record) != nil || record.NativeSkillPolicy != nil || (record.SchemaVersion != "local-runtime-identity/v1" && record.SchemaVersion != "local-runtime-identity/v2" && record.SchemaVersion != "local-runtime-identity/v3") {
		return false
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	if start, err := decoder.Token(); err != nil || start != json.Delim('{') {
		return false
	}
	seen := map[string]bool{}
	for decoder.More() {
		token, err := decoder.Token()
		key, ok := token.(string)
		if err != nil || !ok || seen[key] {
			return false
		}
		seen[key] = true
		var value json.RawMessage
		if decoder.Decode(&value) != nil {
			return false
		}
	}
	_, err := decoder.Token()
	return err == nil && decoder.Decode(new(any)) == io.EOF
}
