package skillinstall

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"testing"
)

func TestOperationContractSamples(t *testing.T) {
	f, p, request := readyInstall(t)
	installed, err := f.store.Apply(nil, request)
	if err != nil {
		t.Fatal(err)
	}
	claim, err := f.store.claim(context.Background(), installed.InstallID)
	if err != nil {
		t.Fatal(err)
	}
	// Normalize volatile source/authority/target values using the existing signed
	// plan DTO fixture. This is not an apply-able real target or current authority.
	raw, err := os.ReadFile("../../testdata/contracts/local-skill-install-plan.v1.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(raw, &claim.Plan); err != nil {
		t.Fatal(err)
	}
	claim.InstallID = installID(claim.Plan.PlanID)
	claim.CreatedAt = "2026-09-11T03:00:01Z"
	doc, err := document(claim, false)
	if err != nil {
		t.Fatal(err)
	}
	claim.Signature, err = f.store.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	if !manifestValid(*claim) {
		t.Fatal("normalized fixture lost manifest binding")
	}
	raw, err = f.store.ownerBytes(claim, "")
	if err != nil {
		t.Fatal(err)
	}
	var owner Owner
	if err := json.Unmarshal(raw, &owner); err != nil {
		t.Fatal(err)
	}
	installed.InstallID = claim.InstallID
	installed.PlanID = claim.Plan.PlanID
	installed.ClaimSignature = claim.Signature
	installed.RecordedAt = "2026-09-11T03:00:02Z"
	doc, err = document(installed, false)
	if err != nil {
		t.Fatal(err)
	}
	installed.Signature, err = f.store.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	request.PlanID = claim.Plan.PlanID
	request.PlanSignature = claim.Plan.Signature
	request.ActorID = p.ActorID
	for name, value := range map[string]any{"apply": request, "claim": claim, "owner": owner, "operation": installed} {
		raw, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		raw = append(raw, '\n')
		path := "../../testdata/contracts/local-skill-install-" + name + ".v1.sample.json"
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(raw, expected) {
			t.Fatal("operation contract differs", name, err)
		}
	}
}
