package inventory

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

// normalizeInventorySample extends the fixture's existing synthetic instance
// IDs to WorkBuddy's locators and signed directory metadata. These are public
// test-key signatures, not evidence about a real host or production identity.
func normalizeInventorySample(t *testing.T, rep *Report) {
	t.Helper()
	var replacements []string
	for i, candidate := range rep.Candidates {
		if id := candidate.Attributes["instance_id"]; id != "" {
			replacements = append(replacements, id, fmt.Sprintf("hi-%032x", i+1))
		}
	}
	for _, relationship := range rep.Relationships {
		if strings.HasPrefix(relationship.SourceID, "agent:workbuddy:") {
			t.Fatal("this fixture has no WorkBuddy Skills; extend its relationship identity normalization explicitly")
		}
	}
	key, err := signing.FromSeed(bytes.Repeat([]byte{4}, 32))
	if err != nil {
		t.Fatal(err)
	}
	metadataHash := func(id string) string {
		raw, err := canon.Marshal(map[string]any{"instance_id": id, "configuration_directory_exists": true})
		if err != nil {
			t.Fatal(err)
		}
		return fmt.Sprintf("%x", sha256.Sum256(raw))
	}
	// Verify the actual discovery evidence before making the documented
	// synthetic projection. Neither a changed payload nor a bad signature can
	// become valid merely by updating this golden sample.
	for _, evidence := range rep.Evidence {
		raw, err := json.Marshal(evidence)
		if err != nil {
			t.Fatal(err)
		}
		var doc map[string]any
		if err := json.Unmarshal(raw, &doc); err != nil {
			t.Fatal(err)
		}
		delete(doc, "signature")
		if !signing.VerifyCanonical(key.Public(), doc, evidence.Signature) {
			t.Fatalf("invalid source evidence signature: %s", evidence.EvidenceID)
		}
		if evidence.SourceType == "manifest" && strings.HasPrefix(evidence.SourceLocator, "workbuddy://instances/") {
			id := strings.TrimPrefix(evidence.SourceLocator, "workbuddy://instances/")
			if evidence.ContentHash != metadataHash(id) {
				t.Fatal("WorkBuddy directory evidence metadata changed")
			}
		}
	}
	rewrite := func(pairs []string) {
		raw, err := json.Marshal(rep)
		if err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal([]byte(strings.NewReplacer(pairs...).Replace(string(raw))), rep); err != nil {
			t.Fatal(err)
		}
	}
	rewrite(replacements)
	var evidenceIDs []string
	for i := range rep.Evidence {
		evidence := &rep.Evidence[i]
		if !strings.HasPrefix(evidence.SourceLocator, "workbuddy://instances/") {
			continue
		}
		oldID := evidence.EvidenceID
		if evidence.SourceType == "manifest" {
			evidence.ContentHash = metadataHash(strings.TrimPrefix(evidence.SourceLocator, "workbuddy://instances/"))
		}
		builder := &run{opts: Options{Key: key, Version: evidence.ConnectorVersion}, now: evidence.ObservedAt, report: &Report{}}
		evidence.EvidenceID = builder.evidence(evidence.SourceType, evidence.SourceLocator, evidence.ContentHash)
		evidence.Signature = signDoc(key, *evidence)
		evidenceIDs = append(evidenceIDs, oldID, evidence.EvidenceID)
	}
	rewrite(evidenceIDs)
	sort.Slice(rep.Evidence, func(i, j int) bool { return rep.Evidence[i].EvidenceID < rep.Evidence[j].EvidenceID })
}
