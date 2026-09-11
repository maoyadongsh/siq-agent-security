package skillinstall

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/importsource"
)

var updateRequestPattern = regexp.MustCompile(`^up-[a-f0-9]{32}$`)
var updatePlanPattern = regexp.MustCompile(`^sup-[a-f0-9]{64}$`)

type UpdateStageRequest struct {
	SchemaVersion             string `json:"schema_version"`
	RequestID                 string `json:"request_id"`
	OperationSignature        string `json:"operation_signature"`
	CandidateGrantID          string `json:"candidate_grant_id"`
	ExpectedCandidateRevision int    `json:"expected_candidate_revision"`
	ExpectedPreviousRevision  int    `json:"expected_previous_revision"`
	ExpectedBindingSignature  string `json:"expected_binding_signature"`
	ActorID                   string `json:"actor_id"`
}
type UpdatePlan struct {
	SchemaVersion             string              `json:"schema_version"`
	UpdateID                  string              `json:"update_id"`
	RequestID                 string              `json:"request_id"`
	Record                    Record              `json:"record"`
	CandidateSource           importsource.Source `json:"candidate_source"`
	CandidateGrantID          string              `json:"candidate_grant_id"`
	CandidateRevision         int                 `json:"candidate_revision"`
	CandidateSignature        string              `json:"candidate_signature"`
	CandidatePermissionDigest string              `json:"candidate_permission_digest"`
	PreviousRevision          int                 `json:"previous_revision"`
	PreviousSignature         string              `json:"previous_signature"`
	BindingSignature          string              `json:"binding_signature"`
	RetainedInstallID         string              `json:"retained_install_id"`
	RevokePreviousGrant       bool                `json:"revoke_previous_grant"`
	ActorID                   string              `json:"actor_id"`
	CreatedAt                 string              `json:"created_at"`
	ExpiresAt                 string              `json:"expires_at"`
	FileCount                 int                 `json:"file_count"`
	TotalBytes                int64               `json:"total_bytes"`
	PlatformChanges           bool                `json:"platform_changes"`
	RuntimeVerified           bool                `json:"runtime_verified"`
	RequiresConfirmation      bool                `json:"requires_confirmation"`
	Signature                 string              `json:"signature"`
}

func validUpdateRequest(r UpdateStageRequest) bool {
	actor := Request{"local-skill-install-stage-create/v1", "is-" + strings.Repeat("0", 32), r.CandidateGrantID, r.ExpectedCandidateRevision, "hi-" + strings.Repeat("0", 32), "update", r.ActorID}
	return r.SchemaVersion == "local-skill-update-stage-create/v1" && updateRequestPattern.MatchString(r.RequestID) && signaturePattern.MatchString(r.OperationSignature) && validRequest(actor) && r.ExpectedPreviousRevision >= 0 && (r.ExpectedBindingSignature == "" || signaturePattern.MatchString(r.ExpectedBindingSignature))
}
func (p UpdatePlan) request() UpdateStageRequest {
	op := ""
	if p.Record.Operation != nil {
		op = p.Record.Operation.Signature
	}
	return UpdateStageRequest{"local-skill-update-stage-create/v1", p.RequestID, op, p.CandidateGrantID, p.CandidateRevision, p.PreviousRevision, p.BindingSignature, p.ActorID}
}
func (p UpdatePlan) identity() (string, error) {
	doc, err := document(map[string]any{"request": p.request(), "installation_claim_signature": p.Record.ClaimSignature, "installation_plan_signature": p.Record.Plan.Signature, "candidate_source": p.CandidateSource, "candidate_signature": p.CandidateSignature, "candidate_permission_digest": p.CandidatePermissionDigest, "previous_signature": p.PreviousSignature, "retained_install_id": p.RetainedInstallID, "revoke_previous_grant": p.RevokePreviousGrant}, true)
	if err != nil {
		return "", err
	}
	raw, err := canon.Marshal(doc)
	if err != nil {
		return "", err
	}
	return "sup-" + hash(raw), nil
}
func (s *Store) updateRecord(id string) string {
	return filepath.Join(s.dir, "update-plans", id+".json")
}
func (s *Store) updateStage(id string) string { return filepath.Join(s.dir, "update-stages", id) }
func (s *Store) inspectUpdate(ctx context.Context, id string, req UpdateStageRequest) (*UpdatePlan, error) {
	comparison, err := s.compareUpdate(ctx, id, UpdateCompareRequest{"local-skill-update-compare/v1", req.OperationSignature, req.CandidateGrantID, req.ExpectedCandidateRevision})
	if err != nil {
		return nil, err
	}
	if comparison.CandidateGrant.Status != "approved" || comparison.PreviousRevision != req.ExpectedPreviousRevision {
		return nil, ErrChanged
	}
	_, installed, err := s.historicalRecord(ctx, id)
	if err != nil {
		return nil, err
	}
	old, revision, binding, retained, err := s.removalAuthority(ctx, installed)
	if err != nil || old.Signature != comparison.PreviousGrant.Signature || revision != req.ExpectedPreviousRevision || binding != req.ExpectedBindingSignature {
		return nil, ErrChanged
	}
	if _, err := s.verifyTarget(ctx, installed, true); err != nil {
		return nil, err
	}
	digest, err := grant.PermissionDigest(comparison.CandidateGrant)
	if err != nil {
		return nil, ErrChanged
	}
	candidate, _, err := s.imports.Load(ctx, comparison.CandidateSource.ImportID)
	if err != nil {
		return nil, sourceError(ctx, err)
	}
	p := &UpdatePlan{SchemaVersion: "local-skill-update-plan/v1", RequestID: req.RequestID, Record: comparison.Record, CandidateSource: comparison.CandidateSource, CandidateGrantID: req.CandidateGrantID, CandidateRevision: req.ExpectedCandidateRevision, CandidateSignature: comparison.CandidateGrant.Signature, CandidatePermissionDigest: digest, PreviousRevision: revision, PreviousSignature: old.Signature, BindingSignature: binding, RetainedInstallID: retained, RevokePreviousGrant: retained == "", ActorID: req.ActorID, FileCount: len(candidate.Files), RequiresConfirmation: true}
	for _, f := range candidate.Files {
		if reservedMetadata(f.Path) {
			return nil, ErrReservedMetadata
		}
		p.TotalBytes += f.Bytes
	}
	for _, d := range candidate.Directories {
		if reservedMetadata(d) {
			return nil, ErrReservedMetadata
		}
	}
	if err := s.boundary("update_stage_checked"); err != nil {
		return nil, ErrUnavailable
	}
	latestOld, latestRevision, latestBinding, latestRetained, err := s.removalAuthority(ctx, installed)
	if err != nil || latestRevision != revision || latestOld.Signature != old.Signature || latestBinding != binding || latestRetained != retained {
		return nil, ErrChanged
	}
	latestNext, nextRevision, err := s.authority.GetGrantWithSeq(p.CandidateGrantID)
	if err != nil || latestNext == nil || nextRevision != p.CandidateRevision || latestNext.Signature != p.CandidateSignature || !grant.Verify(s.key.Public(), *latestNext) || latestNext.Status != "approved" || grant.ValidateLifetime(*latestNext, s.now()) != nil {
		return nil, ErrChanged
	}
	if err := s.removalStarted(id); err != nil {
		return nil, err
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	p.UpdateID, err = p.identity()
	if err != nil {
		return nil, ErrInvalid
	}
	return p, nil
}
func (s *Store) readUpdatePlan(ctx context.Context, id string) (*UpdatePlan, error) {
	if !updatePlanPattern.MatchString(id) {
		return nil, ErrInvalid
	}
	var p UpdatePlan
	if err := s.readSigned(ctx, s.updateRecord(id), &p); err != nil {
		return nil, err
	}
	if p.SchemaVersion != "local-skill-update-plan/v1" || p.UpdateID != id || !validUpdateRequest(p.request()) || p.Record.RecordedStatus != "installed_unverified" || p.Record.Operation == nil || !validInstallID(p.Record.InstallID) || !signaturePattern.MatchString(p.CandidateSignature) || !signaturePattern.MatchString(p.PreviousSignature) || !digestPattern.MatchString(p.CandidatePermissionDigest) || p.FileCount < 1 || p.FileCount > 2000 || p.TotalBytes < 0 || p.TotalBytes > 64<<20 || p.PlatformChanges || p.RuntimeVerified || !p.RequiresConfirmation {
		return nil, ErrChanged
	}
	if p.RevokePreviousGrant {
		if p.RetainedInstallID != "" {
			return nil, ErrChanged
		}
	} else if !validInstallID(p.RetainedInstallID) || p.RetainedInstallID == p.Record.InstallID || p.BindingSignature == "" {
		return nil, ErrChanged
	}
	if _, err := p.CandidateSource.Canonical(); err != nil {
		return nil, ErrChanged
	}
	identity, err := p.identity()
	if err != nil || identity != id {
		return nil, ErrChanged
	}
	created, e1 := time.Parse(time.RFC3339Nano, p.CreatedAt)
	expires, e2 := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	if e1 != nil || e2 != nil || expires.Sub(created) != planTTL {
		return nil, ErrChanged
	}
	return &p, nil
}
func (s *Store) updatePlanTime(p *UpdatePlan) error {
	created, _ := time.Parse(time.RFC3339Nano, p.CreatedAt)
	expires, _ := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	now := s.now()
	if now.Before(created) || !now.Before(expires) {
		return ErrExpired
	}
	return nil
}
func (s *Store) loadUpdatePlan(ctx context.Context, id string) (*UpdatePlan, error) {
	p, err := s.readUpdatePlan(ctx, id)
	if err != nil {
		return nil, err
	}
	if err := s.updatePlanTime(p); err != nil {
		return nil, err
	}
	current, err := s.inspectUpdate(ctx, p.Record.InstallID, p.request())
	if err != nil {
		return nil, err
	}
	if current.UpdateID != p.UpdateID || current.FileCount != p.FileCount || current.TotalBytes != p.TotalBytes || !sameDocument(current.Record, p.Record) {
		return nil, ErrChanged
	}
	if err := s.imports.VerifyUpdateCopy(ctx, p.CandidateSource.ImportID, filepath.Join(s.updateStage(id), "payload")); err != nil {
		return nil, sourceError(ctx, err)
	}
	current, err = s.inspectUpdate(ctx, p.Record.InstallID, p.request())
	if err != nil {
		return nil, err
	}
	if current.UpdateID != p.UpdateID || current.FileCount != p.FileCount || current.TotalBytes != p.TotalBytes {
		return nil, ErrChanged
	}
	if err := s.updatePlanTime(p); err != nil {
		return nil, err
	}
	return p, nil
}
func (s *Store) LoadUpdatePlan(ctx context.Context, id string) (*UpdatePlan, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	select {
	case stageSlot <- struct{}{}:
		defer func() { <-stageSlot }()
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	return s.loadUpdatePlan(ctx, id)
}
func (s *Store) checkUpdateRequest(ctx context.Context, p *UpdatePlan) error {
	dir := filepath.Join(s.dir, "update-plans")
	if err := checkDirectories(dir); err != nil {
		return err
	}
	f, err := os.Open(dir)
	if err != nil {
		return ErrUnavailable
	}
	names, err := f.Readdirnames(maxStages*2 + 1)
	f.Close()
	if err != nil && err != io.EOF {
		return ErrUnavailable
	}
	if len(names) > maxStages*2 {
		return ErrLimit
	}
	if len(names) == maxStages*2 {
		if _, err := os.Lstat(s.updateRecord(p.UpdateID)); os.IsNotExist(err) {
			return ErrLimit
		} else if err != nil {
			return ErrUnavailable
		}
	}
	for _, name := range names {
		if strings.HasPrefix(name, ".operation-") {
			continue
		}
		id := strings.TrimSuffix(name, ".json")
		if name != id+".json" {
			return ErrChanged
		}
		existing, err := s.readUpdatePlan(ctx, id)
		if err != nil {
			return err
		}
		if existing.RequestID == p.RequestID && existing.UpdateID != p.UpdateID {
			return ErrConflict
		}
	}
	return ctx.Err()
}
func (s *Store) StageUpdate(ctx context.Context, id string, req UpdateStageRequest) (*UpdatePlan, bool, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if !validUpdateRequest(req) {
		return nil, false, ErrInvalid
	}
	select {
	case stageSlot <- struct{}{}:
		defer func() { <-stageSlot }()
	case <-ctx.Done():
		return nil, false, ctx.Err()
	}
	p, err := s.inspectUpdate(ctx, id, req)
	if err != nil {
		return nil, false, err
	}
	if err := s.checkUpdateRequest(ctx, p); err != nil {
		return nil, false, err
	}
	if _, err := os.Lstat(s.updateRecord(p.UpdateID)); err == nil {
		current, err := s.loadUpdatePlan(ctx, p.UpdateID)
		return current, err == nil, err
	} else if !os.IsNotExist(err) {
		return nil, false, ErrUnavailable
	}
	parent := filepath.Join(s.dir, "update-stages")
	if err := checkDirectories(parent); err != nil {
		return nil, false, err
	}
	f, err := os.Open(parent)
	if err != nil {
		return nil, false, ErrUnavailable
	}
	names, err := f.Readdirnames(maxStages)
	f.Close()
	if err != nil && err != io.EOF {
		return nil, false, ErrUnavailable
	}
	if len(names) >= maxStages {
		return nil, false, ErrLimit
	}
	stage := s.updateStage(p.UpdateID)
	if err := os.Mkdir(stage, 0700); err != nil {
		if os.IsExist(err) {
			return nil, false, ErrConflict
		}
		return nil, false, ErrUnavailable
	}
	published := false
	defer func() {
		if !published {
			_ = os.RemoveAll(stage)
		}
	}()
	payload := filepath.Join(stage, "payload")
	if err := os.Mkdir(payload, 0700); err != nil {
		return nil, false, ErrUnavailable
	}
	copy, err := s.imports.CopyForUpdate(ctx, p.CandidateSource.ImportID, payload)
	if err != nil {
		return nil, false, sourceError(ctx, err)
	}
	if copy.ArtifactDigest != p.CandidateSource.ArtifactDigest || copy.AnalysisSHA256 != p.CandidateSource.AnalysisSHA256 {
		return nil, false, ErrChanged
	}
	if err := s.boundary("update_copied"); err != nil {
		return nil, false, ErrUnavailable
	}
	if err := s.imports.VerifyUpdateCopy(ctx, p.CandidateSource.ImportID, payload); err != nil {
		return nil, false, sourceError(ctx, err)
	}
	current, err := s.inspectUpdate(ctx, id, req)
	if err != nil {
		return nil, false, err
	}
	if current.UpdateID != p.UpdateID || current.FileCount != p.FileCount || current.TotalBytes != p.TotalBytes {
		return nil, false, ErrChanged
	}
	now := s.now().UTC()
	p.CreatedAt = now.Format(time.RFC3339Nano)
	p.ExpiresAt = now.Add(planTTL).Format(time.RFC3339Nano)
	doc, err := document(p, false)
	if err != nil {
		return nil, false, ErrUnavailable
	}
	p.Signature, err = s.key.SignCanonical(doc)
	if err != nil {
		return nil, false, ErrUnavailable
	}
	if err := ctx.Err(); err != nil {
		return nil, false, err
	}
	if err := publishDocument(s.updateRecord(p.UpdateID), p); err != nil {
		return nil, false, err
	}
	published = true
	if err := s.boundary("update_plan_published"); err != nil {
		return nil, false, ErrUnavailable
	}
	return p, false, nil
}
