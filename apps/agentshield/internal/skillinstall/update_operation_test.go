package skillinstall

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func confirmedUpdate(t *testing.T) (fixture, *UpdatePlan, UpdateCommitRequest) {
	t.Helper()
	f, op, req := readyUpdate(t)
	p, _, err := f.store.StageUpdate(nil, op.InstallID, req)
	if err != nil {
		t.Fatal(err)
	}
	return f, p, UpdateCommitRequest{"local-skill-update-commit/v1", p.UpdateID, p.Signature, p.ActorID, true}
}
func recoverUpdateRequest(v *UpdateView) UpdateRecoverRequest {
	return UpdateRecoverRequest{"local-skill-update-recover/v1", v.UpdateID, v.Claim.Signature, v.Claim.ActorID, true}
}
func TestConfirmedUpdateReplacesFilesWithoutActivatingAuthority(t *testing.T) {
	f, p, req := confirmedUpdate(t)
	s := f.store
	expected, err := os.ReadFile(filepath.Join(s.updateStage(p.UpdateID), "payload", "SKILL.md"))
	if err != nil {
		t.Fatal(err)
	}
	before, rev, err := s.authority.GetGrantWithSeq(p.CandidateGrantID)
	if err != nil {
		t.Fatal(err)
	}
	v, err := s.CommitUpdate(nil, req)
	if err != nil {
		t.Fatal(err)
	}
	if v.Status != "updated_unverified" || v.Result == nil || v.Result.RuntimeVerified || v.Removal.Status != "removed" || v.Installation.Status != "installed_unverified" {
		t.Fatal(v)
	}
	actual, err := os.ReadFile(filepath.Join(f.root, "skills", "example", "SKILL.md"))
	if err != nil || string(actual) != string(expected) {
		t.Fatal("replacement differs", err)
	}
	old, _, err := s.authority.GetGrantWithSeq(p.Record.Plan.GrantID)
	if err != nil || old.Status != "revoked" {
		t.Fatal("old authority not withdrawn", err)
	}
	after, afterRev, err := s.authority.GetGrantWithSeq(p.CandidateGrantID)
	if err != nil || rev != afterRev || before.Signature != after.Signature {
		t.Fatal("new authority changed", err)
	}
	if err := s.ValidateRuntimeGrant(context.Background(), after); err == nil {
		t.Fatal("update activated runtime")
	}
	expiry, _ := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	s.now = func() time.Time { return expiry.Add(time.Hour) }
	retry, err := s.CommitUpdate(nil, req)
	if err != nil || !sameDocument(v, retry) {
		t.Fatal("historical retry", err)
	}
	if _, err := s.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", v.Claim.ReplacementPlan.PlanID, v.Claim.ReplacementPlan.Signature, p.ActorID, true}); !errors.Is(err, ErrConflict) {
		t.Fatal("ordinary apply consumed update", err)
	}
	// History remains readable after a user changes the successful target.
	if err := os.WriteFile(filepath.Join(f.root, "skills", "example", "notes.txt"), []byte("user"), 0600); err != nil {
		t.Fatal(err)
	}
	retry, err = s.ReadUpdate(nil, p.UpdateID)
	if err != nil || retry.Result.Signature != v.Result.Signature {
		t.Fatal(err)
	}
}
func TestUpdateCommitRequiresExactUnexpiredConfirmation(t *testing.T) {
	for _, name := range []string{"confirm", "actor", "signature", "expired", "target", "source", "cancelled"} {
		t.Run(name, func(t *testing.T) {
			f, p, req := confirmedUpdate(t)
			s := f.store
			ctx := context.Background()
			switch name {
			case "confirm":
				req.ConfirmUpdate = false
			case "actor":
				req.ActorID = "other"
			case "signature":
				req.PlanSignature = strings.Repeat("e", 128)
			case "expired":
				end, _ := time.Parse(time.RFC3339Nano, p.ExpiresAt)
				s.now = func() time.Time { return end }
			case "target":
				if err := os.WriteFile(filepath.Join(f.root, "skills", "example", "notes.txt"), []byte("user"), 0600); err != nil {
					t.Fatal(err)
				}
			case "source":
				if err := os.WriteFile(filepath.Join(s.authority.Dir, "skill-imports", "blobs", p.CandidateSource.ImportID, "payload", "SKILL.md"), []byte("changed"), 0600); err != nil {
					t.Fatal(err)
				}
			case "cancelled":
				var cancel context.CancelFunc
				ctx, cancel = context.WithCancel(ctx)
				cancel()
			}
			if _, err := s.CommitUpdate(ctx, req); err == nil {
				t.Fatal("invalid confirmation accepted")
			}
			if err := s.removalStarted(p.Record.InstallID); err != nil {
				t.Fatal("old removal started", err)
			}
			if _, err := os.Lstat(s.updateOperationPath(p.UpdateID, "claim")); !os.IsNotExist(err) {
				t.Fatal("invalid declaration persisted", err)
			}
		})
	}
}
func TestUpdateRecoveryBeforeRemovalPreservesOldVersion(t *testing.T) {
	f, p, req := confirmedUpdate(t)
	s := f.store
	s.boundary = func(phase string) error {
		if phase == "update_claim_published" {
			return errors.New("fixture stop")
		}
		return nil
	}
	if _, err := s.CommitUpdate(nil, req); err == nil {
		t.Fatal("fault ignored")
	}
	s.boundary = func(string) error { return nil }
	v, err := s.ReadUpdate(nil, p.UpdateID)
	if err != nil || v.Status != "confirmed" {
		t.Fatal(v, err)
	}
	r := recoverUpdateRequest(v)
	wrong := r
	wrong.ActorID = "other"
	if _, err := s.RecoverUpdate(nil, wrong); !errors.Is(err, ErrConflict) {
		t.Fatal("actor replaced", err)
	}
	v, err = s.RecoverUpdate(nil, r)
	if err != nil || v.Status != "aborted" {
		t.Fatal(v, err)
	}
	if _, err := s.ReadOperation(nil, p.Record.InstallID); err != nil {
		t.Fatal("old installation altered", err)
	}
	g, _, err := s.authority.GetGrantWithSeq(p.Record.Plan.GrantID)
	if err != nil || g.Status != "approved" {
		t.Fatal("old permission changed")
	}
	v, err = s.CommitUpdate(nil, req)
	if err != nil || v.Status != "aborted" {
		t.Fatal("aborted request restarted", err)
	}
}
func TestUpdateRecoveryAfterOldRemovalDoesNotReviveOrOverwrite(t *testing.T) {
	f, p, req := confirmedUpdate(t)
	s := f.store
	s.boundary = func(phase string) error {
		if phase == "update_install_plan_published" {
			return errors.New("fixture stop")
		}
		return nil
	}
	if _, err := s.CommitUpdate(nil, req); err == nil {
		t.Fatal("fault ignored")
	}
	s.boundary = func(string) error { return nil }
	v, err := s.ReadUpdate(nil, p.UpdateID)
	if err != nil || v.Status != "installing_candidate" {
		t.Fatal(v, err)
	}
	expiry, _ := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	s.now = func() time.Time { return expiry }
	if _, err := s.CommitUpdate(nil, req); !errors.Is(err, ErrExpired) {
		t.Fatal("expired continuation installs", err)
	}
	v, err = s.RecoverUpdate(nil, recoverUpdateRequest(v))
	if err != nil || v.Status != "aborted" {
		t.Fatal(v, err)
	}
	n := v.Claim.ReplacementPlan
	if _, err := s.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", n.PlanID, n.Signature, n.ActorID, true}); !errors.Is(err, ErrConflict) {
		t.Fatal("aborted plan bypass", err)
	}
	target := filepath.Join(f.root, "skills", "example")
	if err := os.Mkdir(target, 0700); err != nil {
		t.Fatal(err)
	}
	user := filepath.Join(target, "user.txt")
	if err := os.WriteFile(user, []byte("owned by user"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.RecoverUpdate(nil, recoverUpdateRequest(v)); err != nil {
		t.Fatal(err)
	}
	if raw, err := os.ReadFile(user); err != nil || string(raw) != "owned by user" {
		t.Fatal("retry deleted user file", err)
	}
	g, _, err := s.authority.GetGrantWithSeq(p.Record.Plan.GrantID)
	if err != nil || g.Status != "revoked" {
		t.Fatal("revoked permission revived")
	}
}
func TestUpdateFailureRecoversOnlyOwnedCandidate(t *testing.T) {
	f, p, req := confirmedUpdate(t)
	s := f.store
	s.boundary = func(phase string) error {
		if phase == "before_result" {
			return errors.New("fixture failure")
		}
		return nil
	}
	v, err := s.CommitUpdate(nil, req)
	if err == nil || v == nil || v.Installation == nil || v.Installation.Status != "rolled_back" {
		t.Fatal(v, err)
	}
	s.boundary = func(string) error { return nil }
	v, err = s.RecoverUpdate(nil, recoverUpdateRequest(v))
	if err != nil || v.Status != "aborted" {
		t.Fatal(v, err)
	}
	if _, err := os.Lstat(filepath.Join(f.root, "skills", "example")); !os.IsNotExist(err) {
		t.Fatal("failed candidate remains", err)
	}
	g, _, err := s.authority.GetGrantWithSeq(p.Record.Plan.GrantID)
	if err != nil || g.Status != "revoked" {
		t.Fatal("old permission revived")
	}
}
func TestUpdateSuccessfulInstallCanFinishAfterLostResponseAndExpiry(t *testing.T) {
	f, p, req := confirmedUpdate(t)
	s := f.store
	s.boundary = func(phase string) error {
		if phase == "update_before_result" {
			return errors.New("fixture failure")
		}
		return nil
	}
	v, err := s.CommitUpdate(nil, req)
	if err == nil || v == nil || v.Installation == nil || v.Installation.Status != "installed_unverified" {
		t.Fatal(v, err)
	}
	s.boundary = func(string) error { return nil }
	end, _ := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	s.now = func() time.Time { return end }
	v, err = s.RecoverUpdate(nil, recoverUpdateRequest(v))
	if err != nil || v.Status != "updated_unverified" {
		t.Fatal(v, err)
	}
	if _, err := s.ReadOperation(nil, v.Installation.InstallID); err != nil {
		t.Fatal("successful candidate removed", err)
	}
}

func TestUpdateTransactionsSerializeOriginalAndPreserveAbortHistory(t *testing.T) {
	f, p, req := confirmedUpdate(t)
	s := f.store
	stageReq := p.request()
	stageReq.RequestID = "up-" + strings.Repeat("b", 32)
	other, _, err := s.StageUpdate(nil, p.Record.InstallID, stageReq)
	if err != nil {
		t.Fatal(err)
	}
	s.boundary = func(phase string) error {
		if phase == "update_claim_published" {
			return errors.New("fixture stop")
		}
		return nil
	}
	if _, err := s.CommitUpdate(nil, req); err == nil {
		t.Fatal("fault ignored")
	}
	s.boundary = func(string) error { return nil }
	otherReq := UpdateCommitRequest{"local-skill-update-commit/v1", other.UpdateID, other.Signature, other.ActorID, true}
	if _, err := s.CommitUpdate(nil, otherReq); !errors.Is(err, ErrConflict) {
		t.Fatal("overlapping transaction accepted", err)
	}
	v, err := s.ReadUpdate(nil, p.UpdateID)
	if err != nil {
		t.Fatal(err)
	}
	v, err = s.RecoverUpdate(nil, recoverUpdateRequest(v))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.CommitUpdate(nil, otherReq); err != nil {
		t.Fatal("aborted transaction prevented new review", err)
	}
	historical, err := s.ReadUpdate(nil, p.UpdateID)
	if err != nil || historical.Result.Signature != v.Result.Signature {
		t.Fatal("later removal invalidated abort history", err)
	}
}

func TestUpdateInterruptedCandidatePreservesUnknownFiles(t *testing.T) {
	f, _, req := confirmedUpdate(t)
	s := f.store
	user := filepath.Join(f.root, "skills", "example", "user.txt")
	s.boundary = func(phase string) error {
		if phase == "before_result" {
			if err := os.WriteFile(user, []byte("user data"), 0600); err != nil {
				return err
			}
			return errors.New("fixture failure")
		}
		return nil
	}
	v, err := s.CommitUpdate(nil, req)
	if err == nil || v == nil || v.Installation == nil || v.Installation.Status != "recovery_required" {
		t.Fatal(v, err)
	}
	s.boundary = func(string) error { return nil }
	if _, err := s.RecoverUpdate(nil, recoverUpdateRequest(v)); !errors.Is(err, ErrRecoveryRequired) {
		t.Fatal("unknown file not protected", err)
	}
	if raw, err := os.ReadFile(user); err != nil || string(raw) != "user data" {
		t.Fatal("unknown file changed", err)
	}
	// The fixture owner explicitly moves their file away before retrying cleanup.
	if err := os.Rename(user, filepath.Join(f.root, "saved-user.txt")); err != nil {
		t.Fatal(err)
	}
	v, err = s.RecoverUpdate(nil, recoverUpdateRequest(v))
	if err != nil || v.Status != "aborted" {
		t.Fatal(v, err)
	}
}
func TestUpdateChangedTargetAndCorruptClaimDoNotWithdraw(t *testing.T) {
	for _, kind := range []string{"target", "claim", "copy"} {
		t.Run(kind, func(t *testing.T) {
			f, p, req := confirmedUpdate(t)
			s := f.store
			s.boundary = func(phase string) error {
				if phase == "update_claim_published" {
					return errors.New("fixture stop")
				}
				return nil
			}
			if _, err := s.CommitUpdate(nil, req); err == nil {
				t.Fatal("fault ignored")
			}
			s.boundary = func(string) error { return nil }
			path := filepath.Join(f.root, "skills", "example", "user.txt")
			if kind == "claim" {
				path = s.updateOperationPath(p.UpdateID, "claim")
			}
			if kind == "copy" {
				path = filepath.Join(s.updateStage(p.UpdateID), "payload", "SKILL.md")
			}
			if err := os.WriteFile(path, []byte("changed"), 0600); err != nil {
				t.Fatal(err)
			}
			if _, err := s.CommitUpdate(nil, req); err == nil {
				t.Fatal("changed content accepted")
			}
			if err := s.removalStarted(p.Record.InstallID); err != nil {
				t.Fatal("old withdrawal started", err)
			}
		})
	}
}
func TestUpdateTransactionCapacityReservesFinalRecord(t *testing.T) {
	for _, count := range []int{254, 255} {
		t.Run(fmt.Sprint(count), func(t *testing.T) {
			f, p, req := confirmedUpdate(t)
			s := f.store
			for i := 0; i < count; i++ {
				if err := os.WriteFile(filepath.Join(s.dir, "update-operations", fmt.Sprintf(".operation-%03d", i)), nil, 0600); err != nil {
					t.Fatal(err)
				}
			}
			v, err := s.CommitUpdate(nil, req)
			if count == 254 {
				if err != nil || v.Status != "updated_unverified" {
					t.Fatal(v, err)
				}
				again, err := s.CommitUpdate(nil, req)
				if err != nil || again.Result.Signature != v.Result.Signature {
					t.Fatal(err)
				}
				entries, err := os.ReadDir(filepath.Join(s.dir, "update-operations"))
				if err != nil || len(entries) != 256 {
					t.Fatal(len(entries), err)
				}
			} else {
				if !errors.Is(err, ErrLimit) {
					t.Fatal("capacity accepted", v, err)
				}
				if err := s.removalStarted(p.Record.InstallID); err != nil {
					t.Fatal("capacity failure withdrew old", err)
				}
			}
		})
	}
}
