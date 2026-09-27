package pending

import (
	"encoding/json"
	"strings"
	"testing"
)

func localFixture() Record {
	return Record{Schema: LocalSchemaID, RecordedAt: "2026-09-28T00:00:00Z", Platform: "workbuddy", EnforcementMode: "block", Outcome: "deny", Reason: "invalid managed hook input", Origin: "local_hook", Stage: "parse", ReasonCode: "workbuddy_input_invalid"}
}

func TestLocalPendingStrictVersionedReader(t *testing.T) {
	raw, _ := json.Marshal(localFixture())
	var rec Record
	if err := decodeLocalRecord(raw, &rec); err != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{
		strings.Replace(string(raw), `"signed":false`, `"signed":true`, 1),
		strings.Replace(string(raw), `"signed":false`, `"signed":false,"signed":false`, 1),
		strings.Replace(string(raw), `"signed":false`, `"signed":null`, 1),
		strings.TrimSuffix(string(raw), "}") + `,"params":{"token":"secret"}}`,
		strings.TrimSuffix(string(raw), "}") + `,"native_call_id":"unverified"}`,
		strings.Replace(string(raw), "local_hook", "online_policy", 1),
		strings.Replace(string(raw), "deny", "allow", 1),
		strings.Replace(string(raw), "workbuddy_input_invalid", "bad reason code", 1),
		strings.Repeat(" ", LocalRecordLimit) + string(raw),
	} {
		if err := decodeLocalRecord([]byte(bad), &rec); err == nil {
			t.Fatal("malformed local record accepted")
		}
	}
}

func TestLocalPendingPreservesLegacyAndV2InOneLog(t *testing.T) {
	dir := t.TempDir()
	if err := Append(dir, Record{Platform: "hermes", EnforcementMode: "block", Outcome: "deny", Reason: "legacy"}); err != nil {
		t.Fatal(err)
	}
	if err := Append(dir, localFixture()); err != nil {
		t.Fatal(err)
	}
	var schemas []string
	n, err := Promote(dir, func(r Record) error { schemas = append(schemas, r.Schema); return nil })
	if err != nil || n != 2 || strings.Join(schemas, ",") != SchemaID+","+LocalSchemaID {
		t.Fatal("version compatibility lost", n, schemas, err)
	}
}
