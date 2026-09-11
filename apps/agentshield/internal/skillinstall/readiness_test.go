package skillinstall

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/state"
	"strings"
	"testing"
)

func TestReadinessIsReadOnlyAndRestoresInterruptedPreparation(t *testing.T) {
	f, op, req := readyActivation(t)
	s := f.store
	for i := 0; i < 2; i++ {
		r, err := s.ReadReadiness(nil, op.InstallID)
		if err != nil || r.Status != "not_prepared" || r.Binding != nil || r.StateRevision != req.ExpectedRevision {
			t.Fatal(r, err)
		}
	}
	if _, err := os.Stat(s.bindingPath(f.request.GrantID)); !os.IsNotExist(err) {
		t.Fatal("read published binding", err)
	}
	if _, err := s.ReadGrantReadiness(nil, f.request.GrantID); !errors.Is(err, ErrNotFound) {
		t.Fatal(err)
	}
	s.boundary = func(phase string) error {
		if phase == "runtime_binding_published" {
			return errors.New("interrupt")
		}
		return nil
	}
	if _, err := s.Activate(nil, op.InstallID, req); !errors.Is(err, ErrUnavailable) {
		t.Fatal(err)
	}
	r, err := s.ReadReadiness(nil, op.InstallID)
	if err != nil || r.Status != "incomplete" || r.Binding.ActorID != req.ActorID || r.StateRevision != req.ExpectedRevision {
		t.Fatal(r, err)
	}
	before := r.Binding.Signature
	if _, _, err := s.authority.RuntimeGrantWithSeq(f.request.GrantID); err == nil {
		t.Fatal("read activated interrupted grant")
	}
	s.boundary = func(string) error { return nil }
	if _, err := s.Activate(nil, op.InstallID, req); err != nil {
		t.Fatal(err)
	}
	r, err = s.ReadGrantReadiness(nil, f.request.GrantID)
	if err != nil || r.Status != "prepared" || r.Binding.Signature != before || r.StateRevision != req.ExpectedRevision+1 {
		t.Fatal(r, err)
	}
	again, err := s.ReadReadiness(nil, op.InstallID)
	if err != nil || !sameDocument(r, again) {
		t.Fatal("read mutated preparation", err)
	}
	write(t, filepath.Join(f.root, "skills", "example", "SKILL.md"), "changed")
	if _, err := s.ReadReadiness(nil, op.InstallID); err == nil {
		t.Fatal("stale prepared state")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := s.ReadReadiness(ctx, op.InstallID); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
}

func TestRuntimeReadinessContractSample(t *testing.T) {
	f, op, req := readyActivation(t)
	if _, err := f.store.Activate(nil, op.InstallID, req); err != nil {
		t.Fatal(err)
	}
	r, err := f.store.ReadReadiness(nil, op.InstallID)
	if err != nil {
		t.Fatal(err)
	}
	// Only synthetic fixture clocks, target-derived identifiers and signatures
	// are normalized. The response above came from the full production read.
	r.InstallID = "sin-" + strings.Repeat("1", 64)
	r.Binding.Source.AnalysisSHA256 = strings.Repeat("c", 64)
	r.Grant.AdmissionID, err = r.Binding.Source.AdmissionID()
	if err != nil {
		t.Fatal(err)
	}
	r.Grant.GrantID = "grt-si-" + strings.Repeat("d", 64)
	r.Grant.DesiredPolicyRef.PolicyID = "pol-" + r.Grant.GrantID
	for i := range r.Grant.Facts {
		for j := range r.Grant.Facts[i].EvidenceIDs {
			r.Grant.Facts[i].EvidenceIDs[j] = "evi-si-" + hash([]byte(fmt.Sprintf("fixture-evidence-%d-%d", i, j)))
		}
	}
	r.Grant.CreatedAt = "2026-09-11T03:00:00Z"
	r.Grant.ApprovedBy.ApprovedAt = "2026-09-11T03:00:01Z"
	doc, err := document(r.Grant, false)
	if err != nil {
		t.Fatal(err)
	}
	r.Grant.Signature, err = f.store.key.SignCanonical(doc)
	if err != nil || !grant.Verify(f.store.key.Public(), *r.Grant) {
		t.Fatal("fixture grant signature", err)
	}
	b := r.Binding
	b.GrantID = r.Grant.GrantID
	b.BindingID = bindingID(b.GrantID)
	b.InstallID = r.InstallID
	b.PlanSignature = strings.Repeat("a", 128)
	b.OperationSignature = strings.Repeat("b", 128)
	b.ApprovedSignature = r.Grant.Signature
	b.PermissionDigest, err = grant.PermissionDigest(*r.Grant)
	if err != nil {
		t.Fatal(err)
	}
	b.CreatedAt = "2026-09-11T03:00:02Z"
	doc, err = document(b, false)
	if err != nil {
		t.Fatal(err)
	}
	b.Signature, err = f.store.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := json.MarshalIndent(r, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	raw = append(raw, '\n')
	path := "../../testdata/contracts/local-skill-install-runtime-readiness.v1.sample.json"
	if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
		if err := os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	expected, err := os.ReadFile(path)
	if err != nil || string(expected) != string(raw) {
		t.Fatal("readiness contract differs", err)
	}
}

func TestEmptyToolPreparationAndLegacyBindingAreUnavailable(t *testing.T) {
	f := setupFiles(t, map[string]string{"SKILL.md": "---\nname: example\ndescription: Synthetic instructions only.\n---\nNo tools requested.\n"})
	s := f.store
	p, _, err := s.Stage(nil, f.request)
	if err != nil {
		t.Fatal(err)
	}
	op, err := s.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, p.ActorID, true})
	if err != nil {
		t.Fatal(err)
	}
	req := ActivateRequest{"local-skill-install-activate/v1", op.Signature, p.GrantRevision, p.ActorID, true}
	r, err := s.ReadReadiness(nil, op.InstallID)
	if err != nil || r.Status != "no_tools" || r.Binding != nil {
		t.Fatal(r, err)
	}
	if _, err := s.Activate(nil, op.InstallID, req); !errors.Is(err, ErrNoTools) {
		t.Fatal(err)
	}
	if _, err := os.Stat(s.bindingPath(p.GrantID)); !os.IsNotExist(err) {
		t.Fatal("empty grant published binding", err)
	}
	// Recreate the validly signed empty binding accepted by the previous version.
	v, err := s.ReadView(nil, op.InstallID)
	if err != nil {
		t.Fatal(err)
	}
	b := s.prospectiveBinding(v, p.ActorID)
	doc, err := document(b, false)
	if err != nil {
		t.Fatal(err)
	}
	b.Signature, err = s.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	if err := publishDocument(s.bindingPath(p.GrantID), b); err != nil {
		t.Fatal(err)
	}
	_, err = s.authority.CommitGrant(state.GrantCommit{Grant: *r.Grant, ExpectedRevision: p.GrantRevision, Audit: &state.AuditEvent{Event: "fixture_legacy_empty_binding", Target: p.GrantID}})
	if err != nil {
		t.Fatal(err)
	}
	r, err = s.ReadReadiness(nil, op.InstallID)
	if err != nil || r.Status != "no_tools" || r.Binding == nil {
		t.Fatal(r, err)
	}
	if err := s.ValidateRuntimeGrant(nil, r.Grant); !errors.Is(err, ErrNoTools) {
		t.Fatal("legacy empty binding accepted", err)
	}
}
