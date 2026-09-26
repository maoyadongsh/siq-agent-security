//go:build linux

package main

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestSkillAncestryJournalRestoresExactSignedV2(t *testing.T) {
	state, task, _, _ := skillJournalFixture(t)
	signer, err := NewSignerFromSeed(state.SignerSeed)
	if err != nil {
		t.Fatal(err)
	}
	collection := skillUploadFixture()
	collection.SchemaVersion = "enterprise-skill-collection/v2"
	collection.Observations[0].AncestorSHA256 = []string{collection.Observations[0].LocatorSHA256, strings.Repeat("c", 64)}
	body, digest, err := prepareSkillUpload(task.TaskID, json.RawMessage(`{"roots":["/fixture/skills"],"include":["SKILL.md"]}`), collection, signer)
	if err != nil {
		t.Fatal(err)
	}
	if err := saveSkillUpload(state, task, body, digest); err != nil {
		t.Fatal(err)
	}
	restored, err := loadSkillUpload(state, task)
	if err != nil || restored == nil || string(restored.Body) != string(body) || restored.BatchDigest != digest {
		t.Fatal("v2 replay changed", err)
	}
	collection.Observations[0].AncestorSHA256 = []string{collection.Observations[0].LocatorSHA256}
	changed, changedDigest, err := prepareSkillUpload(task.TaskID, json.RawMessage(`{"roots":["/fixture/skills"],"include":["SKILL.md"]}`), collection, signer)
	if err != nil {
		t.Fatal(err)
	}
	if saveSkillUpload(state, task, changed, changedDigest) == nil {
		t.Fatal("changed ancestry overwrote pending batch")
	}
}
