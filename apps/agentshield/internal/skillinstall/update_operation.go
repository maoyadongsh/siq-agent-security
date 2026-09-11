package skillinstall

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"time"
)

type UpdateCommitRequest struct {
	SchemaVersion string `json:"schema_version"`
	UpdateID      string `json:"update_id"`
	PlanSignature string `json:"plan_signature"`
	ActorID       string `json:"actor_id"`
	ConfirmUpdate bool   `json:"confirm_update"`
}
type UpdateRecoverRequest struct {
	SchemaVersion   string `json:"schema_version"`
	UpdateID        string `json:"update_id"`
	ClaimSignature  string `json:"claim_signature"`
	ActorID         string `json:"actor_id"`
	ConfirmRecovery bool   `json:"confirm_recovery"`
}
type UpdateClaim struct {
	SchemaVersion   string     `json:"schema_version"`
	UpdateID        string     `json:"update_id"`
	Plan            UpdatePlan `json:"plan"`
	ReplacementPlan Plan       `json:"replacement_plan"`
	ActorID         string     `json:"actor_id"`
	CreatedAt       string     `json:"created_at"`
	Signature       string     `json:"signature"`
}
type UpdateResult struct {
	SchemaVersion         string `json:"schema_version"`
	UpdateID              string `json:"update_id"`
	ClaimSignature        string `json:"claim_signature"`
	Status                string `json:"status"`
	RemovalSignature      string `json:"removal_signature"`
	InstallationSignature string `json:"installation_signature"`
	ActorID               string `json:"actor_id"`
	RecordedAt            string `json:"recorded_at"`
	RuntimeVerified       bool   `json:"runtime_verified"`
	Signature             string `json:"signature"`
}
type UpdateView struct {
	SchemaVersion string        `json:"schema_version"`
	UpdateID      string        `json:"update_id"`
	Claim         UpdateClaim   `json:"claim"`
	Result        *UpdateResult `json:"result"`
	Removal       *RemovalView  `json:"removal"`
	Installation  *Operation    `json:"installation"`
	Status        string        `json:"status"`
}

func (s *Store) updateOperationPath(id, suffix string) string {
	return filepath.Join(s.dir, "update-operations", id+"."+suffix+".json")
}
func (s *Store) replacementPlan(p UpdatePlan) (Plan, error) {
	n := p.Record.Plan
	n.RequestID = "is-" + hash([]byte("update-install:" + p.UpdateID))[:32]
	n.Source = p.CandidateSource
	n.GrantID = p.CandidateGrantID
	n.GrantRevision = p.CandidateRevision
	n.GrantSignature = p.CandidateSignature
	n.GrantPermissionDigest = p.CandidatePermissionDigest
	n.ActorID = p.ActorID
	n.CreatedAt = p.CreatedAt
	n.ExpiresAt = p.ExpiresAt
	n.FileCount = p.FileCount
	n.TotalBytes = p.TotalBytes
	var err error
	n.PlanID, err = n.identity()
	if err != nil {
		return Plan{}, err
	}
	d, err := document(n, false)
	if err != nil {
		return Plan{}, err
	}
	n.Signature, err = s.key.SignCanonical(d)
	return n, err
}
func (s *Store) readUpdateClaim(ctx context.Context, id string) (*UpdateClaim, error) {
	if !updatePlanPattern.MatchString(id) {
		return nil, ErrInvalid
	}
	var c UpdateClaim
	if err := s.readSigned(ctx, s.updateOperationPath(id, "claim"), &c); err != nil {
		return nil, err
	}
	p, err := s.readUpdatePlan(ctx, id)
	if err != nil {
		return nil, err
	}
	n, err := s.replacementPlan(*p)
	if err != nil {
		return nil, err
	}
	created, e1 := time.Parse(time.RFC3339Nano, c.CreatedAt)
	begin, e2 := time.Parse(time.RFC3339Nano, p.CreatedAt)
	end, e3 := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	if c.SchemaVersion != "local-skill-update-claim/v1" || c.UpdateID != id || c.ActorID != p.ActorID || !sameDocument(c.Plan, p) || !sameDocument(c.ReplacementPlan, n) || e1 != nil || e2 != nil || e3 != nil || created.Before(begin) || !created.Before(end) {
		return nil, ErrChanged
	}
	return &c, nil
}
func updateRemovalRequest(c *UpdateClaim) RemoveRequest {
	p := c.Plan
	return RemoveRequest{"local-skill-install-remove/v1", p.Record.Operation.Signature, p.PreviousRevision, p.BindingSignature, c.ActorID, true}
}
func removalMatchesUpdate(c *UpdateClaim, v *RemovalView) bool {
	if v == nil || !sameDocument(c.Plan.Record, v.Record) {
		return false
	}
	if v.Claim == nil {
		return v.Status == "not_requested"
	}
	a := v.Claim
	p := c.Plan
	return a.ActorID == c.ActorID && a.OperationSignature == p.Record.Operation.Signature && a.InstallationClaimSignature == p.Record.ClaimSignature && a.GrantID == p.Record.Plan.GrantID && a.GrantRevision == p.PreviousRevision && a.GrantSignature == p.PreviousSignature && a.BindingSignature == p.BindingSignature && a.RetainedInstallID == p.RetainedInstallID && a.RevokeGrant == p.RevokePreviousGrant
}
func (s *Store) readUpdate(ctx context.Context, id string) (*UpdateView, error) {
	c, err := s.readUpdateClaim(ctx, id)
	if err != nil {
		return nil, err
	}
	var final UpdateResult
	if err := s.readSigned(ctx, s.updateOperationPath(id, "result"), &final); err == nil {
		return s.completedUpdate(ctx, c, &final)
	} else if !errors.Is(err, ErrNotFound) {
		return nil, err
	}
	v := &UpdateView{SchemaVersion: "local-skill-update-view/v1", UpdateID: id, Claim: *c, Status: "confirmed"}
	removal, err := s.ReadRemoval(ctx, c.Plan.Record.InstallID)
	if err != nil {
		return nil, err
	}
	if !removalMatchesUpdate(c, removal) {
		return nil, ErrChanged
	}
	v.Removal = removal
	if removal.Claim != nil {
		v.Status = "removing_previous"
	}
	if removal.Status == "removed" {
		v.Status = "installing_candidate"
	}
	installed, err := s.claim(ctx, installID(c.ReplacementPlan.PlanID))
	if err == nil {
		if !sameDocument(installed.Plan, c.ReplacementPlan) || removal.Status != "removed" {
			return nil, ErrChanged
		}
		op, err := s.readOutcome(ctx, installed)
		if err != nil && !errors.Is(err, ErrRecoveryRequired) {
			return nil, err
		}
		v.Installation = op
		v.Status = "recovery_required"
	} else if !errors.Is(err, ErrNotFound) {
		return nil, err
	}

	return v, nil
}
func (s *Store) ReadUpdate(ctx context.Context, id string) (*UpdateView, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	select {
	case stageSlot <- struct{}{}:
		defer func() { <-stageSlot }()
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	return s.readUpdate(ctx, id)
}
func (s *Store) endUpdate(ctx context.Context, v *UpdateView, status string) (*UpdateView, error) {
	r := UpdateResult{SchemaVersion: "local-skill-update-result/v1", UpdateID: v.UpdateID, ClaimSignature: v.Claim.Signature, Status: status, ActorID: v.Claim.ActorID, RecordedAt: s.now().UTC().Format(time.RFC3339Nano)}
	if v.Removal != nil && v.Removal.Result != nil {
		r.RemovalSignature = v.Removal.Result.Signature
	}
	if v.Installation != nil {
		r.InstallationSignature = v.Installation.Signature
	}
	d, err := document(r, false)
	if err != nil {
		return v, err
	}
	r.Signature, err = s.key.SignCanonical(d)
	if err != nil {
		return v, err
	}
	if err := ctx.Err(); err != nil {
		return v, err
	}
	if err := s.boundary("update_before_result"); err != nil {
		return v, ErrUnavailable
	}
	if err := publishDocument(s.updateOperationPath(v.UpdateID, "result"), r); err != nil {
		return v, err
	}
	return s.readUpdate(ctx, v.UpdateID)
}
func (s *Store) updateOperationCapacity(ctx context.Context, original string) error {
	p := filepath.Join(s.dir, "update-operations")
	if err := checkDirectories(p); err != nil {
		return err
	}
	f, err := os.Open(p)
	if err != nil {
		return ErrUnavailable
	}
	defer f.Close()
	names, err := f.Readdirnames(257)
	if err != nil && err != io.EOF {
		return ErrUnavailable
	}
	// Reserve room for both the immutable claim and its eventual result.
	if len(names) >= 255 {
		return ErrLimit
	}
	count := 0
	for _, n := range names {
		if filepath.Ext(n) == ".json" && len(n) > len(".claim.json") && n[len(n)-len(".claim.json"):] == ".claim.json" {
			count++
			id := n[:len(n)-len(".claim.json")]
			c, err := s.readUpdateClaim(ctx, id)
			if err != nil {
				return err
			}
			if c.Plan.Record.InstallID == original {
				var final UpdateResult
				if err := s.readSigned(ctx, s.updateOperationPath(id, "result"), &final); errors.Is(err, ErrNotFound) {
					return ErrConflict
				} else if err != nil {
					return err
				}
				if _, err := s.completedUpdate(ctx, c, &final); err != nil {
					return err
				}
			}
		}
	}
	if count >= 64 {
		return ErrLimit
	}
	return nil
}

// prepareUpdateInstallation never publishes an ordinary plan. Only a complete
// private copy matching the already signed update claim may be reused.
func (s *Store) prepareUpdateInstallation(ctx context.Context, c *UpdateClaim) error {
	p := c.ReplacementPlan
	if err := s.checkAuthority(ctx, p, true); err != nil {
		return err
	}
	if err := s.imports.VerifyUpdateCopy(ctx, p.Source.ImportID, filepath.Join(s.updateStage(c.UpdateID), "payload")); err != nil {
		return sourceError(ctx, err)
	}
	if err := s.checkRequest(p); err != nil {
		return err
	}
	if _, err := s.readPlan(p.PlanID); errors.Is(err, ErrNotFound) {
		parent := filepath.Join(s.dir, "plans")
		if err := checkDirectories(parent); err != nil {
			return err
		}
		f, err := os.Open(parent)
		if err != nil {
			return ErrUnavailable
		}
		names, err := f.Readdirnames(maxStages*2 + 1)
		f.Close()
		if err != nil && err != io.EOF {
			return ErrUnavailable
		}
		if len(names) >= maxStages*2 {
			return ErrLimit
		}
	} else if err != nil {
		return err
	}
	path := s.stage(p.PlanID)
	if _, err := os.Lstat(path); err == nil {
		if err := checkDirectories(path); err != nil {
			return err
		}
		if err := s.imports.VerifyInstallationCopy(ctx, p.Source.ImportID, filepath.Join(path, "payload")); err != nil {
			return sourceError(ctx, err)
		}
		return s.checkAuthority(ctx, p, true)
	} else if !os.IsNotExist(err) {
		return ErrUnavailable
	}
	parent := filepath.Dir(path)
	if err := checkDirectories(parent); err != nil {
		return err
	}
	f, err := os.Open(parent)
	if err != nil {
		return ErrUnavailable
	}
	names, err := f.Readdirnames(maxStages + 1)
	f.Close()
	if err != nil && err != io.EOF {
		return ErrUnavailable
	}
	if len(names) >= maxStages {
		return ErrLimit
	}
	if err := os.Mkdir(path, 0700); err != nil {
		return ErrConflict
	}
	if err := os.Mkdir(filepath.Join(path, "payload"), 0700); err != nil {
		return ErrUnavailable
	}
	_, err = s.imports.CopyForInstallation(ctx, p.Source.ImportID, filepath.Join(path, "payload"))
	if err != nil {
		return sourceError(ctx, err)
	}
	return s.checkAuthority(ctx, p, true)
}

// CommitUpdate is explicitly confirmed. The caller holds the state writer lock.
func (s *Store) CommitUpdate(ctx context.Context, r UpdateCommitRequest) (*UpdateView, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if r.SchemaVersion != "local-skill-update-commit/v1" || !r.ConfirmUpdate || !updatePlanPattern.MatchString(r.UpdateID) || !signaturePattern.MatchString(r.PlanSignature) {
		return nil, ErrInvalid
	}
	select {
	case stageSlot <- struct{}{}:
		defer func() { <-stageSlot }()
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	c, err := s.readUpdateClaim(ctx, r.UpdateID)
	if errors.Is(err, ErrNotFound) {
		if _, e := os.Lstat(s.updateOperationPath(r.UpdateID, "result")); !os.IsNotExist(e) {
			return nil, ErrChanged
		}
		p, e := s.loadUpdatePlan(ctx, r.UpdateID)
		if e != nil {
			return nil, e
		}
		if p.Signature != r.PlanSignature || p.ActorID != r.ActorID {
			return nil, ErrChanged
		}
		if e = s.updateOperationCapacity(ctx, p.Record.InstallID); e != nil {
			return nil, e
		}
		if e = s.operationCapacity(); e != nil {
			return nil, e
		}
		n, e := s.replacementPlan(*p)
		if e != nil {
			return nil, e
		}
		c = &UpdateClaim{SchemaVersion: "local-skill-update-claim/v1", UpdateID: r.UpdateID, Plan: *p, ReplacementPlan: n, ActorID: r.ActorID, CreatedAt: s.now().UTC().Format(time.RFC3339Nano)}
		d, e := document(c, false)
		if e != nil {
			return nil, e
		}
		c.Signature, e = s.key.SignCanonical(d)
		if e != nil {
			return nil, e
		}
		if e = s.updatePlanTime(p); e != nil {
			return nil, e
		}
		if e = publishDocument(s.updateOperationPath(r.UpdateID, "claim"), c); e != nil {
			return nil, e
		}
	} else if err != nil {
		return nil, err
	}
	if c.Plan.Signature != r.PlanSignature || c.ActorID != r.ActorID {
		return nil, ErrConflict
	}
	if err := s.boundary("update_claim_published"); err != nil {
		return nil, ErrUnavailable
	}
	v, err := s.readUpdate(ctx, r.UpdateID)
	if err != nil {
		return nil, err
	}
	if v.Result != nil {
		return v, nil
	}
	// A durable successful installation is historical evidence even after expiry.
	if v.Installation != nil && v.Installation.Status == "installed_unverified" {
		return s.endUpdate(ctx, v, "updated_unverified")
	}
	if _, e := s.claim(ctx, installID(c.ReplacementPlan.PlanID)); e == nil {
		return v, ErrRecoveryRequired
	} else if !errors.Is(e, ErrNotFound) {
		return v, e
	}
	if err := s.reserveUpdateReplacement(ctx, c); err != nil {
		return v, err
	}
	if err := s.prepareUpdateInstallation(ctx, c); err != nil {
		return v, err
	}
	if err := s.operationCapacity(); err != nil {
		return v, err
	}
	if v.Removal.Claim == nil {
		if _, err := s.loadUpdatePlan(ctx, c.UpdateID); err != nil {
			return v, err
		}
	}
	removal, err := s.remove(ctx, c.Plan.Record.InstallID, updateRemovalRequest(c))
	if err != nil {
		return nil, err
	}
	if !removalMatchesUpdate(c, removal) || removal.Status != "removed" {
		return v, ErrChanged
	}
	if err := s.boundary("update_previous_removed"); err != nil {
		return nil, ErrUnavailable
	}
	v, err = s.readUpdate(ctx, r.UpdateID)
	if err != nil {
		return nil, err
	}
	p := c.ReplacementPlan
	if err := s.checkAuthority(ctx, p, true); err != nil {
		return v, err
	}
	if err := s.imports.VerifyUpdateCopy(ctx, p.Source.ImportID, filepath.Join(s.updateStage(c.UpdateID), "payload")); err != nil {
		return v, sourceError(ctx, err)
	}
	if existing, e := s.readPlan(p.PlanID); e == nil {
		if !sameDocument(existing, p) {
			return v, ErrChanged
		}
	} else if errors.Is(e, ErrNotFound) {
		if e = s.publish(p); e != nil {
			return v, e
		}
	} else {
		return v, e
	}
	if err := s.boundary("update_install_plan_published"); err != nil {
		return nil, ErrUnavailable
	}
	_, applyErr := s.apply(ctx, ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, c.ActorID, true})
	v, err = s.readUpdate(ctx, r.UpdateID)
	if err != nil {
		return nil, err
	}
	if v.Installation != nil && v.Installation.Status == "installed_unverified" {
		return s.endUpdate(ctx, v, "updated_unverified")
	}
	if applyErr != nil {
		return v, applyErr
	}
	return v, ErrRecoveryRequired
}

// RecoverUpdate aborts uncompleted work, never restores authority or installs.
func (s *Store) RecoverUpdate(ctx context.Context, r UpdateRecoverRequest) (*UpdateView, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if r.SchemaVersion != "local-skill-update-recover/v1" || !r.ConfirmRecovery || !updatePlanPattern.MatchString(r.UpdateID) || !signaturePattern.MatchString(r.ClaimSignature) {
		return nil, ErrInvalid
	}
	select {
	case stageSlot <- struct{}{}:
		defer func() { <-stageSlot }()
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	v, err := s.readUpdate(ctx, r.UpdateID)
	if err != nil {
		return nil, err
	}
	c := &v.Claim
	if c.Signature != r.ClaimSignature || c.ActorID != r.ActorID {
		return nil, ErrConflict
	}
	if v.Result != nil {
		return v, nil
	}
	if v.Installation != nil && v.Installation.Status == "installed_unverified" {
		return s.endUpdate(ctx, v, "updated_unverified")
	}
	if v.Removal.Claim != nil && v.Removal.Status != "removed" {
		if _, err := s.remove(ctx, c.Plan.Record.InstallID, updateRemovalRequest(c)); err != nil {
			return v, err
		}
	}
	id := installID(c.ReplacementPlan.PlanID)
	if _, err := s.claim(ctx, id); err == nil {
		if _, err := s.recover(ctx, id, c.ActorID); err != nil {
			return v, err
		}
	} else if !errors.Is(err, ErrNotFound) {
		return v, err
	}
	v, err = s.readUpdate(ctx, r.UpdateID)
	if err != nil {
		return nil, err
	}
	return s.endUpdate(ctx, v, "aborted")
}

// The durable reservation survives abort, so an ordinary apply cannot restart
// a replacement whose original update confirmation has already been consumed.
func (s *Store) updateReplacementReserved(id string) error {
	p := filepath.Join(s.dir, "update-installations", id+".json")
	if err := checkDirectories(filepath.Dir(p)); err != nil {
		return err
	}
	if _, err := os.Lstat(p); os.IsNotExist(err) {
		return nil
	} else if err != nil {
		return ErrUnavailable
	}
	return ErrConflict
}
func (s *Store) reserveUpdateReplacement(ctx context.Context, c *UpdateClaim) error {
	p := filepath.Join(s.dir, "update-installations", c.ReplacementPlan.PlanID+".json")
	var existing UpdateClaim
	if err := s.readSigned(ctx, p, &existing); err == nil {
		if !sameDocument(existing, c) {
			return ErrChanged
		}
		return nil
	} else if !errors.Is(err, ErrNotFound) {
		return err
	}
	return publishDocument(p, c)
}

// Final results refer to historical records; a later user operation must not
// alter the meaning of a previously aborted or successful update.
func (s *Store) completedUpdate(ctx context.Context, c *UpdateClaim, r *UpdateResult) (*UpdateView, error) {
	v := &UpdateView{SchemaVersion: "local-skill-update-view/v1", UpdateID: c.UpdateID, Claim: *c, Result: r, Status: r.Status}
	at, e := time.Parse(time.RFC3339Nano, r.RecordedAt)
	start, _ := time.Parse(time.RFC3339Nano, c.CreatedAt)
	if r.SchemaVersion != "local-skill-update-result/v1" || r.UpdateID != c.UpdateID || r.ClaimSignature != c.Signature || r.ActorID != c.ActorID || r.RuntimeVerified || e != nil || at.Before(start) {
		return nil, ErrChanged
	}
	if r.RemovalSignature != "" {
		removal, err := s.ReadRemoval(ctx, c.Plan.Record.InstallID)
		if err != nil {
			return nil, err
		}
		if !removalMatchesUpdate(c, removal) || removal.Status != "removed" || removal.Result == nil || removal.Result.Signature != r.RemovalSignature {
			return nil, ErrChanged
		}
		v.Removal = removal
	}
	if r.InstallationSignature != "" {
		installed, err := s.claim(ctx, installID(c.ReplacementPlan.PlanID))
		if err != nil {
			return nil, err
		}
		if !sameDocument(installed.Plan, c.ReplacementPlan) {
			return nil, ErrChanged
		}
		op, err := s.readOutcome(ctx, installed)
		if err != nil {
			return nil, err
		}
		if op.Signature != r.InstallationSignature {
			return nil, ErrChanged
		}
		v.Installation = op
	}
	switch r.Status {
	case "updated_unverified":
		if v.Removal == nil || v.Installation == nil || v.Installation.Status != "installed_unverified" {
			return nil, ErrChanged
		}
	case "aborted":
		if v.Installation != nil && (v.Removal == nil || v.Installation.Status != "rolled_back") {
			return nil, ErrChanged
		}
	default:
		return nil, ErrChanged
	}
	return v, nil
}
