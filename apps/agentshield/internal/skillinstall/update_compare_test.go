package skillinstall

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/state"
)

func updateFixture(t *testing.T) (fixture, *Operation, UpdateCompareRequest) {
	t.Helper()
	f, op := installedInspection(t)
	source := t.TempDir()
	write(t, filepath.Join(source, "SKILL.md"), "---\nname: example\ndescription: Read the new synthetic report.\nallowed-tools: read_file write_file\n---\nRead version two.\n")
	write(t, filepath.Join(source, "references", "guide.md"), "New reference")
	id := "si-" + strings.Repeat("e", 32)
	if _, _, _, err := f.store.imports.Create(nil, skillimport.CreateRequest{SchemaVersion: "local-skill-import-create/v1", ImportID: id, SourceKind: "local_dir", Path: source, ActorID: "human"}); err != nil {
		t.Fatal(err)
	}
	_, derived, err := f.store.imports.PermissionAdmission(nil, id)
	if err != nil {
		t.Fatal(err)
	}
	if err := f.store.authority.PutImportAdmission(derived); err != nil {
		t.Fatal(err)
	}
	built, err := grant.BuildImported(derived.Admission, grant.Options{Key: f.store.key, Platform: "hermes", Subject: grant.Subject{Type: "agent_instance", ID: "hri-" + strings.Repeat("b", 32)}}, "human", "ip-"+strings.Repeat("f", 32))
	if err != nil {
		t.Fatal(err)
	}
	revision, err := f.store.authority.CommitGrant(state.GrantCommit{Grant: built.Grant, ExpectedRevision: -1, DesiredPolicy: built.DesiredPolicy, Audit: &state.AuditEvent{Event: "fixture_candidate", Target: built.Grant.GrantID}})
	if err != nil {
		t.Fatal(err)
	}
	return f, op, UpdateCompareRequest{"local-skill-update-compare/v1", op.Signature, built.Grant.GrantID, revision}
}
func TestUpdateComparisonFixedBaselineAndUnapprovedCandidate(t *testing.T) {
	f, op, req := updateFixture(t)
	s := f.store
	before, rev, err := s.authority.GetGrantWithSeq(f.request.GrantID)
	if err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(f.root, "skills", "example", "SKILL.md")
	original, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	out, err := s.CompareUpdate(nil, op.InstallID, req)
	if err != nil || out.CandidateGrant.Status == "approved" || out.ContentChangesTotal != 4 || out.PlatformChanges || out.RuntimeVerified || !out.RequiresConfirmation || out.Record.Operation.Signature != op.Signature {
		t.Fatal(out, err)
	}
	if out.PermissionChangesTotal == 0 {
		t.Fatal("new tool permission not shown")
	}
	changes := map[string]UpdateContentChange{}
	for _, change := range out.ContentChanges {
		changes[change.PathDisplay] = change
	}
	if changes["SKILL.md"].Before == nil || changes["SKILL.md"].After == nil || changes["skill-manifest.json"].After != nil || changes["references"].After.Kind != "directory" {
		t.Fatal("wrong file comparison")
	}
	after, afterRev, err := s.authority.GetGrantWithSeq(before.GrantID)
	if err != nil || afterRev != rev || after.Signature != before.Signature {
		t.Fatal("comparison changed old authority", err)
	}
	candidate, _, err := s.authority.GetGrantWithSeq(req.CandidateGrantID)
	if err != nil || candidate.Signature != out.CandidateGrant.Signature {
		t.Fatal("comparison approved candidate", err)
	}
	if raw, err := os.ReadFile(target); err != nil || string(raw) != string(original) {
		t.Fatal("comparison modified target", err)
	}
	if err := s.removalStarted(op.InstallID); err != nil {
		t.Fatal("comparison started removal", err)
	}
	// Local drift and corruption of the old source cannot rewrite the signed baseline.
	write(t, target, "user modification")
	write(t, filepath.Join(s.authority.Dir, "skill-imports", "blobs", f.importID, "payload", "SKILL.md"), "old source unavailable")
	again, err := s.CompareUpdate(nil, op.InstallID, req)
	if err != nil || !reflect.DeepEqual(out.ContentChanges, again.ContentChanges) {
		t.Fatal("old source or target substituted baseline", err)
	}
}
func TestUpdateComparisonRejectsChangedInputs(t *testing.T) {
	for _, kind := range []string{"operation", "revision", "same_grant", "candidate_content", "candidate_race", "grant_race", "removed", "cancelled", "subject", "expired", "rejected", "unsigned", "old_permission_change"} {
		t.Run(kind, func(t *testing.T) {
			f, op, req := updateFixture(t)
			s := f.store
			ctx := context.Background()
			candidatePath := filepath.Join(s.authority.Dir, "skill-imports", "blobs", "si-"+strings.Repeat("e", 32), "payload", "SKILL.md")
			switch kind {
			case "subject", "expired", "rejected", "unsigned", "old_permission_change":
				grantID := req.CandidateGrantID
				if kind == "old_permission_change" {
					grantID = f.request.GrantID
				}
				g, revision, err := s.authority.GetGrantWithSeq(grantID)
				if err != nil {
					t.Fatal(err)
				}
				switch kind {
				case "subject":
					g.Subject.ID = "hri-" + strings.Repeat("c", 32)
				case "expired":
					expired := "2000-01-01T00:00:00Z"
					g.ExpiresAt = &expired
				case "rejected":
					g.Status = "rejected"
				case "unsigned":
					g.Signature = strings.Repeat("0", 128)
				case "old_permission_change":
					g.EnforcementMode = "audit_only"
				}
				if kind != "unsigned" {
					doc, err := document(g, false)
					if err != nil {
						t.Fatal(err)
					}
					g.Signature, err = s.key.SignCanonical(doc)
					if err != nil {
						t.Fatal(err)
					}
				}
				nextRevision, err := s.authority.CommitGrant(state.GrantCommit{Grant: *g, ExpectedRevision: revision, Audit: &state.AuditEvent{Event: "fixture_change", Target: grantID}})
				if err != nil {
					t.Fatal(err)
				}
				if kind != "old_permission_change" {
					req.ExpectedCandidateRevision = nextRevision
				}
			case "operation":
				req.OperationSignature = strings.Repeat("0", 128)
			case "revision":
				req.ExpectedCandidateRevision++
			case "same_grant":
				req.CandidateGrantID = f.request.GrantID
				req.ExpectedCandidateRevision = f.request.ExpectedRevision
			case "candidate_content":
				write(t, candidatePath, "changed")
			case "candidate_race":
				s.boundary = func(p string) error {
					if p == "update_compared" {
						write(t, candidatePath, "changed during comparison")
					}
					return nil
				}
			case "grant_race":
				s.boundary = func(p string) error {
					if p == "update_compared" {
						f.revoke(t)
					}
					return nil
				}
			case "removed":
				if _, err := s.Remove(nil, op.InstallID, removalRequest(t, s, op.InstallID)); err != nil {
					t.Fatal(err)
				}
			case "cancelled":
				var cancel context.CancelFunc
				ctx, cancel = context.WithCancel(ctx)
				cancel()
			}
			if _, err := s.CompareUpdate(ctx, op.InstallID, req); err == nil {
				t.Fatal("changed input accepted")
			}
		})
	}
}
func TestUpdateComparisonContentAndPermissionBudgets(t *testing.T) {
	out := UpdateComparison{ContentChanges: []UpdateContentChange{}, PermissionChanges: []UpdatePermissionChange{}, SettingsChanged: []string{}}
	before := map[string]UpdateContent{"kind": {"file", strings.Repeat("a", 64), 1, false}, "mode": {"file", strings.Repeat("b", 64), 1, false}}
	after := map[string]UpdateContent{"kind": {Kind: "directory"}, "mode": {"file", strings.Repeat("b", 64), 1, true}}
	out.compareContents(before, after)
	if out.ContentChangesTotal != 2 {
		t.Fatal("type/executable changes missed")
	}
	for n := 0; n < 200; n++ {
		after[fmt.Sprintf("file-%03d", n)] = UpdateContent{"file", strings.Repeat("a", 64), 1, false}
	}
	out.ContentChanges = nil
	out.ContentChangesTotal = 0
	out.compareContents(before, after)
	if len(out.ContentChanges) != 200 || out.ContentChangesTotal != 202 || !out.ContentChangesTruncated {
		t.Fatal("content truncation hid total")
	}
	f, _, _ := updateFixture(t)
	g, _, err := f.store.authority.GetGrantWithSeq(f.request.GrantID)
	if err != nil {
		t.Fatal(err)
	}
	out.PreviousGrant = *g
	out.CandidateGrant = *g
	out.CandidateGrant.Facts = append([]grant.Fact{}, g.Facts...)
	for i := range out.CandidateGrant.Facts {
		out.CandidateGrant.Facts[i].FactID = "different"
		out.CandidateGrant.Facts[i].EvidenceIDs = []string{"different"}
	}
	if err := out.comparePermissions(); err != nil || out.PermissionChangesTotal != 0 {
		t.Fatal("evidence identity treated as permission", err)
	}
	out.CandidateGrant.Facts = append(out.CandidateGrant.Facts, out.CandidateGrant.Facts...)
	if err := out.comparePermissions(); err != nil || out.PermissionChangesTotal != 0 {
		t.Fatal("duplicate rule changed scope", err)
	}
	out.CandidateGrant.Facts = append([]grant.Fact{}, g.Facts...)
	out.CandidateGrant.Facts[0].Conditions = map[string]any{"require_approval": true}
	out.CandidateGrant.EnforcementMode = "audit_only"
	if err := out.comparePermissions(); err != nil || out.PermissionChangesTotal != 2 || len(out.SettingsChanged) != 1 {
		t.Fatal("condition/mode change missed", err)
	}
	for i := 0; i < 201; i++ {
		fact := g.Facts[0]
		fact.Action = fmt.Sprintf("tool.%03d", i)
		out.CandidateGrant.Facts = append(out.CandidateGrant.Facts, fact)
	}
	out.PermissionChanges = nil
	out.PermissionChangesTotal = 0
	out.SettingsChanged = nil
	if err := out.comparePermissions(); err != nil || len(out.PermissionChanges) != 200 || out.PermissionChangesTotal != 203 || !out.PermissionChangesTruncated {
		t.Fatal("permission budget failed", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := f.store.CompareUpdate(ctx, "invalid", UpdateCompareRequest{}); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
}

func TestUpdateComparisonContractSamples(t *testing.T) {
	f, op, req := updateFixture(t)
	out, err := f.store.CompareUpdate(nil, op.InstallID, req)
	if err != nil {
		t.Fatal(err)
	}
	// Normalize time and opaque references only after exercising the actual signed inputs.
	out.Record.Plan.Source.AnalysisSHA256 = strings.Repeat("2", 64)
	out.CandidateSource.AnalysisSHA256 = strings.Repeat("3", 64)
	for i, g := range []*grant.Grant{&out.PreviousGrant, &out.CandidateGrant} {
		g.GrantID = "grt-si-" + strings.Repeat(fmt.Sprint(i+4), 64)
		source := out.Record.Plan.Source
		if i == 1 {
			source = out.CandidateSource
		}
		g.AdmissionID, err = source.AdmissionID()
		if err != nil {
			t.Fatal(err)
		}
		g.CreatedAt = "2026-09-11T05:00:00Z"
		if g.ApprovedBy != nil {
			g.ApprovedBy.ApprovedAt = "2026-09-11T05:00:01Z"
		}
		for j := range g.Facts {
			g.Facts[j].FactID = fmt.Sprintf("fact-%d", j)
			g.Facts[j].EvidenceIDs = []string{fmt.Sprintf("ev-%d", j)}
		}
		if g.DesiredPolicyRef != nil {
			g.DesiredPolicyRef.PolicyID = "pol-" + strings.Repeat(fmt.Sprint(i+4), 64)
		}
		doc, err := document(g, false)
		if err != nil {
			t.Fatal(err)
		}
		g.Signature, err = f.store.key.SignCanonical(doc)
		if err != nil || !grant.Verify(f.store.key.Public(), *g) {
			t.Fatal("normalized grant invalid", err)
		}
	}
	p := &out.Record.Plan
	p.GrantID = out.PreviousGrant.GrantID
	p.GrantSignature = out.PreviousGrant.Signature
	p.GrantPermissionDigest, err = grant.PermissionDigest(out.PreviousGrant)
	if err != nil {
		t.Fatal(err)
	}
	p.TargetLocatorDigest = strings.Repeat("a", 64)
	p.CreatedAt = "2026-09-11T05:00:02Z"
	p.ExpiresAt = "2026-09-11T05:05:02Z"
	p.PlanID, err = p.identity()
	if err != nil {
		t.Fatal(err)
	}
	doc, err := document(p, false)
	if err != nil {
		t.Fatal(err)
	}
	p.Signature, err = f.store.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	out.Record.InstallID = installID(p.PlanID)
	out.Record.ClaimSignature = strings.Repeat("f", 128)
	operation := out.Record.Operation
	operation.InstallID = out.Record.InstallID
	operation.PlanID = p.PlanID
	operation.ClaimSignature = out.Record.ClaimSignature
	operation.RecordedAt = "2026-09-11T05:00:03Z"
	doc, err = document(operation, false)
	if err != nil {
		t.Fatal(err)
	}
	operation.Signature, err = f.store.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	out.CheckedAt = "2026-09-11T05:00:04Z"
	req.OperationSignature = operation.Signature
	req.CandidateGrantID = out.CandidateGrant.GrantID
	for name, value := range map[string]any{"compare": req, "comparison": out} {
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
		if err != nil || string(expected) != string(raw) {
			t.Fatal("update sample differs", name, err)
		}
	}
}
