package skillinstall

import (
	"encoding/json"
	"errors"
	"os"
	"testing"
)

func TestUpdateTransactionContractSamples(t *testing.T) {
	f, p, req := confirmedUpdate(t)
	f.store.boundary = func(phase string) error {
		if phase == "update_claim_published" {
			return errors.New("fixture stop")
		}
		return nil
	}
	if _, err := f.store.CommitUpdate(nil, req); err == nil {
		t.Fatal("fault ignored")
	}
	f.store.boundary = func(string) error { return nil }
	v, err := f.store.ReadUpdate(nil, p.UpdateID)
	if err != nil {
		t.Fatal(err)
	}
	v, err = f.store.RecoverUpdate(nil, recoverUpdateRequest(v))
	if err != nil || v.Status != "aborted" {
		t.Fatal(v, err)
	}
	// Normalize the isolated run using the existing signed preparation fixture.
	raw, err := os.ReadFile("../../testdata/contracts/local-skill-update-plan.v1.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	var plan UpdatePlan
	if err := json.Unmarshal(raw, &plan); err != nil {
		t.Fatal(err)
	}
	c := v.Claim
	c.Plan = plan
	c.UpdateID = plan.UpdateID
	c.CreatedAt = "2026-09-11T05:10:02Z"
	c.ReplacementPlan, err = f.store.replacementPlan(plan)
	if err != nil {
		t.Fatal(err)
	}
	doc, err := document(c, false)
	if err != nil {
		t.Fatal(err)
	}
	c.Signature, err = f.store.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	result := *v.Result
	result.UpdateID = c.UpdateID
	result.ClaimSignature = c.Signature
	result.RecordedAt = "2026-09-11T05:10:03Z"
	doc, err = document(result, false)
	if err != nil {
		t.Fatal(err)
	}
	result.Signature, err = f.store.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	v.Claim = c
	v.UpdateID = c.UpdateID
	v.Result = &result
	req = UpdateCommitRequest{"local-skill-update-commit/v1", c.UpdateID, c.Plan.Signature, c.ActorID, true}
	for name, value := range map[string]any{"commit": req, "recover": recoverUpdateRequest(v), "claim": c, "result": result, "view": v} {
		raw, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		raw = append(raw, '\n')
		path := "../../testdata/contracts/local-skill-update-" + name + ".v1.sample.json"
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil || string(raw) != string(expected) {
			t.Fatal("update transaction sample differs", name, err)
		}
	}
}
