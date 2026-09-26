//go:build linux

package main

import (
	"encoding/json"
	"path/filepath"
	"reflect"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestSkillAncestryStopsAtAuthorizedRootAndPreservesV1(t *testing.T) {
	root := t.TempDir()
	leaf := skillFixture(t, root, "group/skill", "---\nname: sample\n---\n")
	for _, op := range []string{protocol.OpCollectSkills, protocol.OpCollectSkillsV2} {
		params, _ := json.Marshal(collectParams{Plan: skillPlan(root, leaf)})
		response := dispatch(&protocol.Request{ID: "fixture", Op: op, Params: params})
		if !response.OK {
			t.Fatal(response)
		}
		got := response.Result.(protocol.SkillCollection)
		if got.Truncated || len(got.Observations) != 1 {
			t.Fatal(got)
		}
		if op == protocol.OpCollectSkills {
			if got.SchemaVersion != "enterprise-skill-collection/v1" || got.Observations[0].AncestorSHA256 != nil {
				t.Fatal("v1 changed")
			}
			continue
		}
		want := []string{protocol.ContentHash([]byte(leaf)), protocol.ContentHash([]byte(filepath.Dir(leaf))), protocol.ContentHash([]byte(root))}
		if got.SchemaVersion != "enterprise-skill-collection/v2" || !reflect.DeepEqual(got.Observations[0].AncestorSHA256, want) {
			t.Fatal("wrong authorized chain", got)
		}
	}
	got, err := collectSkillsVersion(skillPlan(leaf), true)
	if err != nil || len(got.Observations) != 1 || !reflect.DeepEqual(got.Observations[0].AncestorSHA256, []string{protocol.ContentHash([]byte(leaf))}) {
		t.Fatal("narrow scan disclosed parent chain")
	}
}
