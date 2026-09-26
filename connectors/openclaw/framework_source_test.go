package main

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestFrameworkSourceGroupsOnlySameConfigRoot(t *testing.T) {
	a, b := t.TempDir(), t.TempDir()
	roles := []map[string]string{{"id": "one", "name": "same"}, {"id": "two", "name": "same"}}
	identityConfig(t, a, roles, false)
	identityConfig(t, b, roles, false)
	batch := identityCollect(t, a, b)
	keys := []string{}
	for _, role := range batch.Candidates {
		raw := role.Attributes["framework_source"]
		if strings.Contains(raw, a) || strings.Contains(raw, b) {
			t.Fatal("raw root disclosed")
		}
		var source map[string]string
		if json.Unmarshal([]byte(raw), &source) != nil || source["framework"] != "openclaw" || len(source["instance_key"]) != 64 {
			t.Fatal("invalid source")
		}
		matched := false
		for _, evidence := range batch.Evidence {
			if evidence.EvidenceID == source["evidence_id"] {
				matched = evidence.ContentHash == source["config_sha256"] && evidence.SubjectRef != nil && *evidence.SubjectRef == role.CandidateID
			}
		}
		if !matched {
			t.Fatal("source not bound to role config evidence")
		}
		keys = append(keys, source["instance_key"])
	}
	if len(keys) != 4 || keys[0] != keys[1] || keys[2] != keys[3] || keys[0] == keys[2] {
		t.Fatal("incorrect instance grouping")
	}
	roles[0]["name"] = "renamed"
	identityConfig(t, a, roles, false)
	after := identityCollect(t, a)
	var source map[string]string
	_ = json.Unmarshal([]byte(after.Candidates[0].Attributes["framework_source"]), &source)
	if source["instance_key"] != keys[0] || after.Candidates[0].CandidateID != batch.Candidates[0].CandidateID {
		t.Fatal("rename changed identity")
	}
}
