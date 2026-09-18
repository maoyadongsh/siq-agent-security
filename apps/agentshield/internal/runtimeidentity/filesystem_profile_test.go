package runtimeidentity

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
)

func TestWindowsIdentityRecordRejectsAmbiguousFields(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "contracts", "local-runtime-identity.json"))
	if err != nil {
		t.Fatal(err)
	}
	var old Record
	if err := json.Unmarshal(raw, &old); err != nil {
		t.Fatal(err)
	}
	stable, err := json.Marshal(old)
	if err != nil {
		t.Fatal(err)
	}
	original, _ := canon.Decode(raw)
	decoded, _ := canon.Decode(stable)
	originalBytes, _ := canon.Marshal(original)
	stableBytes, _ := canon.Marshal(decoded)
	if string(originalBytes) != string(stableBytes) {
		t.Fatal("legacy identity signed document changed")
	}
	old.SchemaVersion, old.FilesystemProfile = "local-runtime-identity/v2", "windows-local-drive/v1"
	old.GrantRef.PermissionDigestSchema = "grant-permissions/v2"
	windows, _ := json.Marshal(old)
	var record Record
	if err := json.Unmarshal(windows, &record); err != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{
		`{"platform":"hermes",` + string(windows)[1:],
		strings.Replace(string(windows), `"actor_id":`, `"Actor_ID":`, 1),
		strings.Replace(string(windows), `"filesystem_profile":"windows-local-drive/v1"`, `"filesystem_profile":null`, 1),
		strings.Replace(string(windows), `"local-runtime-identity/v2"`, `"local-runtime-identity/v1"`, 1),
		strings.Replace(string(windows), `"grant-permissions/v2"`, `"grant-permissions/v1"`, 1),
		`{"filesystem_profile":null,` + string(stable)[1:],
	} {
		if json.Unmarshal([]byte(bad), &record) == nil {
			t.Fatal("ambiguous or downgraded identity decoded")
		}
	}
}
