package grant

import (
	"bytes"
	"encoding/json"
	"testing"
)

func TestLegacyGrantWireCannotAcquireProfileMetadata(t *testing.T) {
	g := build(t, "hermes", sampleAdmission()).Grant
	raw, _ := json.Marshal(g)
	for _, name := range []string{"schema_version", "filesystem_profile", "filesystem_bindings", "FILESYSTEM_PROFILE"} {
		for _, value := range []string{`null`, `""`, `{}`} {
			injected := append(append([]byte{}, raw[:len(raw)-1]...), []byte(`,"`+name+`":`+value+`}`)...)
			var decoded Grant
			if json.Unmarshal(injected, &decoded) == nil {
				t.Fatal("legacy signature gained ignored profile fields")
			}
		}
	}
	var decoded Grant
	if err := json.Unmarshal(raw, &decoded); err != nil {
		t.Fatal(err)
	}
	roundTrip, _ := json.Marshal(decoded)
	if !bytes.Equal(raw, roundTrip) || !Verify(key(t).Public(), decoded) {
		t.Fatal("legacy signed bytes changed")
	}
	before, _ := PermissionDigest(g)
	after, _ := PermissionDigest(decoded)
	if before != after {
		t.Fatal("legacy permission digest changed")
	}
}
