//go:build linux

package main

import (
	"bytes"
	"encoding/json"
	"os"
	"testing"
)

func TestRotationJSONFieldShape(t *testing.T) {
	for _, raw := range []string{`null`, `[]`, `{"key":null}`, `{"KEY":"x"}`, `{"key":"x","extra":1}`, `{}`} {
		if _, ok := rotationJSONFields([]byte(raw), []string{"key"}, true); ok {
			t.Fatalf("accepted invalid shape %s", raw)
		}
	}
	if _, ok := rotationJSONFields([]byte(`{"key":"x"}`), []string{"key"}, true); !ok {
		t.Fatal("valid shape rejected")
	}
	if _, ok := rotationJSONFields([]byte(`{}`), []string{"key"}, false); !ok {
		t.Fatal("optional field rejected")
	}
}

func TestRotationRejectsCaseAliasAlongsideCanonicalField(t *testing.T) {
	state := journalFixture(t)
	path, _ := StateFilePath()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]any
	if json.Unmarshal(raw, &fields) != nil {
		t.Fatal("fixture decode")
	}
	fields["SECRET"] = "conflicting-credential"
	raw, _ = json.Marshal(fields)
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadRotationState(); err == nil {
		t.Fatal("conflicting semantic duplicate accepted")
	}
	if _, err := prepareRotationJournal(state); err == nil {
		t.Fatal("preparation bypassed strict state reader")
	}
}

func TestRotationRejectsCaseInsensitiveJSONAliases(t *testing.T) {
	for _, field := range []string{"secret", "control_plane_url", "new_secret", "request", "signature", "device_identity"} {
		t.Run(field, func(t *testing.T) {
			state := journalFixture(t)
			if _, err := prepareRotationJournal(state); err != nil {
				t.Fatal(err)
			}
			isState := field == "secret" || field == "control_plane_url"
			path, _ := rotationJournalPath()
			if isState {
				path, _ = StateFilePath()
			}
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			needle := []byte(`"` + field + `"`)
			changed := bytes.Replace(raw, needle, bytes.ToUpper(needle), 1)
			if bytes.Equal(raw, changed) {
				t.Fatal("test did not mutate a field")
			}
			if err := os.WriteFile(path, changed, 0600); err != nil {
				t.Fatal(err)
			}
			if isState {
				if _, err := loadRotationState(); err == nil {
					t.Fatal("case alias accepted in state")
				}
			} else if _, err := readRotationJournal(state); err == nil {
				t.Fatal("case alias accepted in journal")
			}
			after, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(after, changed) {
				t.Fatal("unsafe file modified")
			}
		})
	}
}
