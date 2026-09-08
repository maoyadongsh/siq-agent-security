package completion

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestCompletionRequiresActualSignedMaterialAndRetainsConflicts(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	store, err := effectevidence.NewStore(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "report")
	before, err := effectevidence.CaptureFile(path, 1024)
	if err != nil {
		t.Fatal(err)
	}
	content := []byte("expected report")
	sum := sha256.Sum256(content)
	expected := hex.EncodeToString(sum[:])
	if err = os.WriteFile(path, content, 0600); err != nil {
		t.Fatal(err)
	}
	after, err := effectevidence.CaptureFile(path, 1024)
	if err != nil {
		t.Fatal(err)
	}
	material, err := effectevidence.FileWrite(before, after, expected)
	if err != nil {
		t.Fatal(err)
	}
	a := effectevidence.Action{ActionID: "a1", DecisionReceiptID: "r1", TaskID: "t1", IntentID: "i1", IntentDigest: strings.Repeat("c", 64), IssuedAt: time.Now().Add(-time.Minute), Authorized: true, Effects: []string{"file.write"}, Resources: runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "filesystem", Value: path}})}
	source := effectevidence.Source{Type: "host_observer", SourceID: "observer", Independence: "host_independent"}
	r, err := store.SubmitFile("e1", material, a, source, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	req := Requirement{RequirementID: "req1", EffectType: "file.write", ResourceRef: after.ResourceRef, ExpectedDigest: expected, MinimumIndependence: "host_independent", MinimumCoverage: "partial"}
	task := Task{ID: a.TaskID, IntentID: a.IntentID, IntentDigest: a.IntentDigest, Requirements: []Requirement{req}}
	lookup := func(string, string) (effectevidence.Action, error) { return a, nil }
	check := func(task Task, records []effectevidence.Record, want string) {
		t.Helper()
		out, err := Evaluate(task, records, key.Public(), lookup, time.Now())
		if err != nil || out.Status != want {
			t.Fatal(out, err, want)
		}
	}
	check(task, nil, "incomplete")
	check(task, []effectevidence.Record{r}, "verified")
	// Two independent observations of the same action disagree: retain conflict,
	// instead of treating the negative record as an ordinary missing effect.
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	absent, err := effectevidence.CaptureFile(path, 1024)
	if err != nil {
		t.Fatal(err)
	}
	failedMaterial, err := effectevidence.FileWrite(before, absent, expected)
	if err != nil {
		t.Fatal(err)
	}
	failedRecord, err := store.SubmitFile("e-failed", failedMaterial, a, source, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	check(task, []effectevidence.Record{failedRecord}, "incomplete")
	check(task, []effectevidence.Record{r, failedRecord}, "conflicting")
	check(task, []effectevidence.Record{failedRecord, r}, "conflicting")
	claimSource := effectevidence.Source{Type: "tool_report", SourceID: "tool", Independence: "self_reported"}
	claim := r.Evidence
	claim.EvidenceID, claim.Signature = "tool-success", ""
	claim.Source, claim.Coverage, claim.Result = claimSource, "unknown", "unknown"
	claimRecord, err := store.Submit(claim, a, claimSource, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	check(task, []effectevidence.Record{claimRecord}, "unknown")
	check(task, []effectevidence.Record{claimRecord, failedRecord}, "conflicting")
	check(task, []effectevidence.Record{failedRecord, claimRecord}, "conflicting")
	otherAction := a
	otherAction.ActionID, otherAction.DecisionReceiptID = "a2", "r2"
	otherFailure, err := store.SubmitFile("e-other-failed", failedMaterial, otherAction, source, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	otherLookup := func(id, receipt string) (effectevidence.Action, error) {
		if id == otherAction.ActionID && receipt == otherAction.DecisionReceiptID {
			return otherAction, nil
		}
		return a, nil
	}
	out, err := Evaluate(task, []effectevidence.Record{r, otherFailure}, key.Public(), otherLookup, time.Now())
	if err != nil || out.Status != "incomplete" {
		t.Fatal("different attempts became conflicting", out, err)
	}
	out, err = Evaluate(task, []effectevidence.Record{claimRecord, otherFailure}, key.Public(), otherLookup, time.Now())
	if err != nil || out.Status != "unknown" {
		t.Fatal("different attempt contradicted tool claim", out, err)
	}
	noMaterial := failedRecord.Evidence
	noMaterial.Signature, noMaterial.EvidenceID = "", "e-failed-no-material"
	unsupportedFailure, err := store.Submit(noMaterial, a, source, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	check(task, []effectevidence.Record{r, unsupportedFailure}, "incomplete")
	check(task, []effectevidence.Record{claimRecord, unsupportedFailure}, "unknown")
	a.AuthorizedAt = time.Now().Add(time.Second)
	check(task, []effectevidence.Record{r}, "conflicting")
	a.AuthorizedAt = time.Time{}
	none := task
	none.Requirements = nil
	check(none, nil, "unknown")
	strict := task
	strict.Requirements = []Requirement{req}
	strict.Requirements[0].MinimumCoverage = "full"
	check(strict, []effectevidence.Record{r}, "unknown")
	strict.Requirements[0] = req
	strict.Requirements[0].MinimumIndependence = "external_independent"
	check(strict, []effectevidence.Record{r}, "unknown")
	wrong := task
	wrong.Requirements = []Requirement{req}
	wrong.Requirements[0].ExpectedDigest = strings.Repeat("d", 64)
	check(wrong, []effectevidence.Record{r}, "conflicting")
	plain := r.Evidence
	plain.Signature = ""
	plain.EvidenceID = "e-no-material"
	plainRecord, err := store.Submit(plain, a, source, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	check(task, []effectevidence.Record{r, plainRecord}, "unknown")
	bad := r
	bad.TaskID = "forged"
	if _, err := Evaluate(task, []effectevidence.Record{bad}, key.Public(), lookup, time.Now()); err == nil {
		t.Fatal("invalid envelope became completion")
	}
	wrongLookup := func(string, string) (effectevidence.Action, error) {
		bad := a
		bad.IntentDigest = strings.Repeat("e", 64)
		return bad, nil
	}
	if _, err := Evaluate(task, []effectevidence.Record{r}, key.Public(), wrongLookup, time.Now()); err == nil {
		t.Fatal("intent mismatch accepted")
	}
	if _, err := Evaluate(task, []effectevidence.Record{r, r}, key.Public(), lookup, time.Now()); err == nil {
		t.Fatal("duplicate evidence accepted")
	}
	a.Authorized = false
	incident, err := store.SubmitFile("e-denied", material, a, source, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	a.Authorized = true
	check(task, []effectevidence.Record{r, incident}, "conflicting")
}
