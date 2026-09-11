package skillinstall

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/state"
)

func readyUpdate(t *testing.T) (fixture, *Operation, UpdateStageRequest) {
	t.Helper()
	f, op, compare := updateFixture(t)
	g, rev, err := f.store.authority.GetGrantWithSeq(compare.CandidateGrantID)
	if err != nil {
		t.Fatal(err)
	}
	approved, err := grant.Approve(*g, grant.Approval{ActorType: "human", ActorID: "human", ApprovedAt: time.Now().UTC().Format(time.RFC3339Nano)}, f.store.key)
	if err != nil {
		t.Fatal(err)
	}
	rev, err = f.store.authority.CommitGrant(state.GrantCommit{Grant: approved, ExpectedRevision: rev, Audit: &state.AuditEvent{Event: "fixture_approve_update", Target: g.GrantID}})
	if err != nil {
		t.Fatal(err)
	}
	return f, op, UpdateStageRequest{"local-skill-update-stage-create/v1", "up-" + strings.Repeat("a", 32), op.Signature, g.GrantID, rev, f.request.ExpectedRevision, "", "human"}
}
func TestUpdateStagePreservesOldVersionAndReusesWithoutRenewal(t *testing.T) {
	f, op, req := readyUpdate(t)
	s := f.store
	target := filepath.Join(f.root, "skills", "example", "SKILL.md")
	old, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	before, rev, err := s.authority.GetGrantWithSeq(f.request.GrantID)
	if err != nil {
		t.Fatal(err)
	}
	p, reused, err := s.StageUpdate(nil, op.InstallID, req)
	if err != nil || reused || p.PlatformChanges || p.RuntimeVerified || !p.RequiresConfirmation || !p.RevokePreviousGrant {
		t.Fatal(p, reused, err)
	}
	source := filepath.Join(s.authority.Dir, "skill-imports", "blobs", p.CandidateSource.ImportID, "payload", "SKILL.md")
	prepared := filepath.Join(s.updateStage(p.UpdateID), "payload", "SKILL.md")
	a, e1 := os.Stat(source)
	b, e2 := os.Stat(prepared)
	if e1 != nil || e2 != nil || os.SameFile(a, b) {
		t.Fatal("update copy is not independent")
	}
	if raw, err := os.ReadFile(target); err != nil || string(raw) != string(old) {
		t.Fatal("old target changed", err)
	}
	after, afterRev, err := s.authority.GetGrantWithSeq(before.GrantID)
	if err != nil || rev != afterRev || after.Signature != before.Signature {
		t.Fatal("preparation withdrew permission", err)
	}
	if err := s.removalStarted(op.InstallID); err != nil {
		t.Fatal("preparation started removal", err)
	}
	again, reused, err := s.StageUpdate(nil, op.InstallID, req)
	if err != nil || !reused || !sameDocument(p, again) {
		t.Fatal("retry changed plan", err)
	}
	if _, err := s.Load(nil, strings.Replace(p.UpdateID, "sup-", "sip-", 1)); !errors.Is(err, ErrNotFound) {
		t.Fatal("ordinary install can consume update plan", err)
	}
	wrong := req
	wrong.ActorID = "other-human"
	if _, _, err := s.StageUpdate(nil, op.InstallID, wrong); !errors.Is(err, ErrConflict) {
		t.Fatal("request identity reused with changed actor", err)
	}
	expires, _ := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	s.now = func() time.Time { return expires }
	if _, _, err := s.StageUpdate(nil, op.InstallID, req); !errors.Is(err, ErrExpired) {
		t.Fatal("expired update renewed", err)
	}
	if raw, err := os.ReadFile(target); err != nil || string(raw) != string(old) {
		t.Fatal("expiry removed old target", err)
	}
}
func TestUpdateStageRejectsUnapprovedAndChangedInputs(t *testing.T) {
	f, op, compare := updateFixture(t)
	req := UpdateStageRequest{"local-skill-update-stage-create/v1", "up-" + strings.Repeat("a", 32), op.Signature, compare.CandidateGrantID, compare.ExpectedCandidateRevision, f.request.ExpectedRevision, "", "human"}
	if _, _, err := f.store.StageUpdate(nil, op.InstallID, req); !errors.Is(err, ErrChanged) {
		t.Fatal("unapproved candidate staged", err)
	}
	for _, kind := range []string{"target", "copy", "source", "revision", "binding", "actor", "cancelled", "authority_race"} {
		t.Run(kind, func(t *testing.T) {
			f, op, req := readyUpdate(t)
			s := f.store
			ctx := context.Background()
			switch kind {
			case "authority_race":
				s.boundary = func(phase string) error {
					if phase == "update_stage_checked" {
						f.revoke(t)
					}
					return nil
				}
			case "target":
				write(t, filepath.Join(f.root, "skills", "example", "user.txt"), "keep")
			case "copy":
				s.boundary = func(phase string) error {
					if phase == "update_copied" {
						p, err := s.inspectUpdate(context.Background(), op.InstallID, req)
						if err != nil {
							t.Fatal(err)
						}
						write(t, filepath.Join(s.updateStage(p.UpdateID), "payload", "SKILL.md"), "changed copy")
					}
					return nil
				}
			case "source":
				s.boundary = func(phase string) error {
					if phase == "update_copied" {
						write(t, filepath.Join(s.authority.Dir, "skill-imports", "blobs", "si-"+strings.Repeat("e", 32), "payload", "SKILL.md"), "changed source")
					}
					return nil
				}
			case "revision":
				req.ExpectedPreviousRevision++
			case "binding":
				req.ExpectedBindingSignature = strings.Repeat("f", 128)
			case "actor":
				req.ActorID = " human "
			case "cancelled":
				var cancel context.CancelFunc
				ctx, cancel = context.WithCancel(ctx)
				cancel()
			}
			if _, _, err := s.StageUpdate(ctx, op.InstallID, req); err == nil {
				t.Fatal("invalid update staged")
			}
			entries, err := os.ReadDir(filepath.Join(s.dir, "update-plans"))
			if err != nil || len(entries) != 0 {
				t.Fatal("failed preparation published plan", err)
			}
			g, _, err := s.authority.GetGrantWithSeq(f.request.GrantID)
			if err != nil || (kind != "authority_race" && g.Status != "approved") {
				t.Fatal("failed preparation changed old grant", err)
			}
		})
	}
}
func TestUpdatePlanReadRechecksTargetSourceCopyAndSignature(t *testing.T) {
	for _, kind := range []string{"target", "source", "copy", "signature", "revoked", "expiry"} {
		t.Run(kind, func(t *testing.T) {
			f, op, req := readyUpdate(t)
			s := f.store
			p, _, err := s.StageUpdate(nil, op.InstallID, req)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := s.LoadUpdatePlan(nil, p.UpdateID); err != nil {
				t.Fatal(err)
			}
			switch kind {
			case "target":
				write(t, filepath.Join(f.root, "skills", "example", "SKILL.md"), "changed old target")
			case "source":
				write(t, filepath.Join(s.authority.Dir, "skill-imports", "blobs", p.CandidateSource.ImportID, "payload", "SKILL.md"), "changed source")
			case "copy":
				write(t, filepath.Join(s.updateStage(p.UpdateID), "payload", "SKILL.md"), "changed staged copy")
			case "signature":
				raw, err := os.ReadFile(s.updateRecord(p.UpdateID))
				if err != nil {
					t.Fatal(err)
				}
				write(t, s.updateRecord(p.UpdateID), strings.Replace(string(raw), p.Signature, strings.Repeat("0", 128), 1))
			case "revoked":
				f.revoke(t)
			case "expiry":
				expires, _ := time.Parse(time.RFC3339Nano, p.ExpiresAt)
				s.now = func() time.Time { return expires }
			}
			if _, err := s.LoadUpdatePlan(nil, p.UpdateID); err == nil {
				t.Fatal("stale update plan accepted", kind)
			}
		})
	}
}
func TestUpdateStageOrphansAndCapacity(t *testing.T) {
	for _, kind := range []string{"orphan", "capacity", "metadata_budget"} {
		t.Run(kind, func(t *testing.T) {
			f, op, req := readyUpdate(t)
			s := f.store
			if kind == "orphan" {
				p, err := s.inspectUpdate(context.Background(), op.InstallID, req)
				if err != nil {
					t.Fatal(err)
				}
				path := filepath.Join(s.updateStage(p.UpdateID), "unknown")
				write(t, path, "keep orphan")
				if _, _, err := s.StageUpdate(nil, op.InstallID, req); !errors.Is(err, ErrConflict) {
					t.Fatal(err)
				}
				if raw, err := os.ReadFile(path); err != nil || string(raw) != "keep orphan" {
					t.Fatal("orphan removed", err)
				}
				return
			}
			if kind == "capacity" {
				for i := 0; i < maxStages-1; i++ {
					if err := os.Mkdir(filepath.Join(s.dir, "update-stages", fmt.Sprintf("orphan-%d", i)), 0700); err != nil {
						t.Fatal(err)
					}
				}
			}
			p, _, err := s.StageUpdate(nil, op.InstallID, req)
			if err != nil {
				t.Fatal("last available slot rejected", err)
			}
			if kind == "metadata_budget" {
				for i := 0; i < maxStages*2-1; i++ {
					write(t, filepath.Join(s.dir, "update-plans", fmt.Sprintf(".operation-orphan-%d", i)), "interrupted temporary")
				}
			}
			if _, reused, err := s.StageUpdate(nil, op.InstallID, req); err != nil || !reused {
				t.Fatal("existing plan unavailable at capacity", err)
			}
			changed := req
			changed.RequestID = "up-" + strings.Repeat("b", 32)
			if _, _, err := s.StageUpdate(nil, op.InstallID, changed); !errors.Is(err, ErrLimit) {
				t.Fatal("capacity exceeded", err)
			}
			if _, err := s.readUpdatePlan(context.Background(), p.UpdateID); err != nil {
				t.Fatal("limit changed prior plan", err)
			}
		})
	}
}
func TestUpdatePlanContractSamples(t *testing.T) {
	f, op, req := readyUpdate(t)
	p, _, err := f.store.StageUpdate(nil, op.InstallID, req)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile("../../testdata/contracts/local-skill-update-comparison.v1.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	var comparison UpdateComparison
	if err := json.Unmarshal(raw, &comparison); err != nil {
		t.Fatal(err)
	}
	g, err := grant.Approve(comparison.CandidateGrant, grant.Approval{ActorType: "human", ActorID: "human", ApprovedAt: "2026-09-11T05:10:00Z"}, f.store.key)
	if err != nil {
		t.Fatal(err)
	}
	p.Record = comparison.Record
	p.CandidateSource = comparison.CandidateSource
	p.CandidateGrantID = g.GrantID
	p.CandidateSignature = g.Signature
	p.CandidatePermissionDigest, err = grant.PermissionDigest(g)
	if err != nil {
		t.Fatal(err)
	}
	p.PreviousRevision = comparison.PreviousRevision
	p.PreviousSignature = comparison.PreviousGrant.Signature
	p.CreatedAt = "2026-09-11T05:10:01Z"
	p.ExpiresAt = "2026-09-11T05:15:01Z"
	p.UpdateID, err = p.identity()
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
	for name, value := range map[string]any{"stage-create": p.request(), "plan": p, "plan-created": map[string]any{"schema_version": "local-skill-update-plan-created/v1", "plan": p, "reused": false}} {
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
			t.Fatal("update stage sample differs", name, err)
		}
	}
}

func TestUpdateStagePreservesOtherInstallationBinding(t *testing.T) {
	f, op, req := readyUpdate(t)
	s := f.store
	other := f.request
	other.RequestID = "is-" + strings.Repeat("e", 32)
	other.DirectoryName = "other"
	p, _, err := s.Stage(nil, other)
	if err != nil {
		t.Fatal(err)
	}
	installed, err := s.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, p.ActorID, true})
	if err != nil {
		t.Fatal(err)
	}
	activated, err := s.Activate(nil, installed.InstallID, ActivateRequest{"local-skill-install-activate/v1", installed.Signature, p.GrantRevision, "human", true})
	if err != nil {
		t.Fatal(err)
	}
	req.ExpectedPreviousRevision = activated.StateRevision
	req.ExpectedBindingSignature = activated.Binding.Signature
	plan, _, err := s.StageUpdate(nil, op.InstallID, req)
	if err != nil || plan.RevokePreviousGrant || plan.RetainedInstallID != installed.InstallID {
		t.Fatal(plan, err)
	}
	g, _, err := s.authority.GetGrantWithSeq(f.request.GrantID)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.ValidateRuntimeGrant(nil, g); err != nil {
		t.Fatal("preparation changed other installation runtime", err)
	}
}
func TestUpdateCopyNamespaceCannotEscapeOrBecomeOrdinaryInstall(t *testing.T) {
	f, op, req := readyUpdate(t)
	p, _, err := f.store.StageUpdate(nil, op.InstallID, req)
	if err != nil {
		t.Fatal(err)
	}
	staged := filepath.Join(f.store.updateStage(p.UpdateID), "payload")
	if _, err := f.store.imports.CopyForInstallation(nil, p.CandidateSource.ImportID, staged); err == nil {
		t.Fatal("ordinary copy accepted update namespace")
	}
	for _, path := range []string{t.TempDir(), filepath.Join(f.store.dir, "stages", "sip-"+strings.Repeat("a", 64), "payload"), filepath.Join(f.root, "skills", "example")} {
		if _, err := f.store.imports.CopyForUpdate(nil, p.CandidateSource.ImportID, path); err == nil {
			t.Fatal("update copy escaped private namespace")
		}
		if err := f.store.imports.VerifyUpdateCopy(nil, p.CandidateSource.ImportID, path); err == nil {
			t.Fatal("update verifier escaped private namespace")
		}
	}
}
