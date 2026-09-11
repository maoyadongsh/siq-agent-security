package skillinstall

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/skillimport"
)

var ErrRecoveryRequired = errors.New("skill_install_recovery_required")
var ErrReservedMetadata = errors.New("skill_install_reserved_metadata")

const ownerName = ".siq-install-owner"

type ApplyRequest struct {
	SchemaVersion  string `json:"schema_version"`
	PlanID         string `json:"plan_id"`
	PlanSignature  string `json:"plan_signature"`
	ActorID        string `json:"actor_id"`
	ConfirmInstall bool   `json:"confirm_install"`
}
type Claim struct {
	SchemaVersion string             `json:"schema_version"`
	InstallID     string             `json:"install_id"`
	Plan          Plan               `json:"plan"`
	Directories   []string           `json:"directories"`
	Files         []skillimport.File `json:"files"`
	ActorID       string             `json:"actor_id"`
	CreatedAt     string             `json:"created_at"`
	Signature     string             `json:"signature"`
}
type Operation struct {
	SchemaVersion   string `json:"schema_version"`
	InstallID       string `json:"install_id"`
	PlanID          string `json:"plan_id"`
	ClaimSignature  string `json:"claim_signature"`
	Status          string `json:"status"`
	ActorID         string `json:"actor_id"`
	RecordedAt      string `json:"recorded_at"`
	RuntimeVerified bool   `json:"runtime_verified"`
	Signature       string `json:"signature"`
}
type Owner struct {
	SchemaVersion     string `json:"schema_version"`
	InstallID         string `json:"install_id"`
	ClaimSignature    string `json:"claim_signature"`
	RelativeDirectory string `json:"relative_directory"`
	Signature         string `json:"signature"`
}

func installID(id string) string { return "sin-" + strings.TrimPrefix(id, "sip-") }
func validInstallID(id string) bool {
	return strings.HasPrefix(id, "sin-") && digestPattern.MatchString(strings.TrimPrefix(id, "sin-"))
}
func (s *Store) operationPath(id, suffix string) string {
	return filepath.Join(s.dir, "operations", id+"."+suffix+".json")
}
func (s *Store) claim(ctx context.Context, id string) (*Claim, error) {
	if !validInstallID(id) {
		return nil, ErrInvalid
	}
	var c Claim
	if err := s.readSigned(ctx, s.operationPath(id, "claim"), &c); err != nil {
		return nil, err
	}
	if c.SchemaVersion != "local-skill-install-claim/v1" || c.InstallID != id || installID(c.Plan.PlanID) != id || c.ActorID != c.Plan.ActorID {
		return nil, ErrChanged
	}
	p, err := s.readPlan(c.Plan.PlanID)
	if err != nil {
		return nil, err
	}
	if !sameDocument(*p, c.Plan) || !manifestValid(c) {
		return nil, ErrChanged
	}
	if _, err := time.Parse(time.RFC3339Nano, c.CreatedAt); err != nil {
		return nil, ErrChanged
	}
	return &c, nil
}
func (s *Store) destination(ctx context.Context, p Plan) (string, string, error) {
	target, err := s.resolve(ctx, p.InstanceID)
	if err != nil || target.InstanceID != p.InstanceID || target.Platform != "hermes" || !filepath.IsAbs(target.Root) || filepath.Clean(target.Root) != target.Root || checkDirectories(target.Root) != nil {
		return "", "", ErrChanged
	}
	destination := filepath.Join(target.Root, "skills", p.DirectoryName)
	if hash([]byte(destination)) != p.TargetLocatorDigest || strings.TrimSuffix(target.Display, "/")+"/skills/"+p.DirectoryName != p.TargetDisplay {
		return "", "", ErrChanged
	}
	parent := filepath.Dir(destination)
	if _, err := os.Lstat(parent); err == nil {
		if err := checkDirectories(parent); err != nil {
			return "", "", err
		}
	} else if !os.IsNotExist(err) {
		return "", "", ErrUnavailable
	}
	return destination, filepath.Join(target.Root, ".siq-agent-security-installs", installID(p.PlanID)), nil
}
func (s *Store) checkAuthority(ctx context.Context, p Plan, full bool) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	g, rev, err := s.authority.GetGrantWithSeq(p.GrantID)
	if err != nil || g == nil || rev != p.GrantRevision || g.Signature != p.GrantSignature || g.Status != "approved" || !grant.Verify(s.key.Public(), *g) || grant.ValidateLifetime(*g, s.now()) != nil {
		return ErrChanged
	}
	if err := s.validTime(&p); err != nil {
		return err
	}
	if full {
		a, err := s.authority.GetAdmission(g.AdmissionID)
		if err != nil {
			return ErrChanged
		}
		if err := s.imports.ValidatePermissionAdmission(ctx, *a); err != nil {
			return sourceError(ctx, err)
		}
		return s.checkAuthority(ctx, p, false)
	}
	return nil
}
func (s *Store) end(c *Claim, status, actor, suffix string) (*Operation, error) {
	result := Operation{SchemaVersion: "local-skill-install-operation/v1", InstallID: c.InstallID, PlanID: c.Plan.PlanID, ClaimSignature: c.Signature, Status: status, ActorID: actor, RecordedAt: s.now().UTC().Format(time.RFC3339Nano)}
	doc, err := document(result, false)
	if err != nil {
		return nil, ErrUnavailable
	}
	result.Signature, err = s.key.SignCanonical(doc)
	if err != nil {
		return nil, ErrUnavailable
	}
	if err := publishDocument(s.operationPath(c.InstallID, suffix), result); err != nil {
		return nil, err
	}
	return &result, nil
}

// ReadOperation validates durable outcome evidence. Installed outcomes also
// require current target contents/ownership; they never activate a Grant.
func (s *Store) ReadOperation(ctx context.Context, id string) (*Operation, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	c, err := s.claim(ctx, id)
	if err != nil {
		return nil, err
	}
	result, err := s.readOutcome(ctx, c)
	if err != nil {
		return nil, err
	}
	if result.Status == "installed_unverified" {
		if _, err := s.verifyTarget(ctx, c, true); err != nil {
			return nil, err
		}
	}
	return result, nil
}

// readOutcome validates only signed historical evidence. It is not a current
// target or runtime permission check, so callers must label it accordingly.
func (s *Store) readOutcome(ctx context.Context, c *Claim) (*Operation, error) {
	id := c.InstallID
	var result Operation
	err := s.readSigned(ctx, s.operationPath(id, "recovered"), &result)
	if errors.Is(err, ErrNotFound) {
		err = s.readSigned(ctx, s.operationPath(id, "result"), &result)
	}
	if errors.Is(err, ErrNotFound) {
		return nil, ErrRecoveryRequired
	}
	if err != nil {
		return nil, err
	}
	request := c.Plan.request()
	request.ActorID = result.ActorID
	if result.SchemaVersion != "local-skill-install-operation/v1" || result.InstallID != id || result.PlanID != c.Plan.PlanID || result.ClaimSignature != c.Signature || result.RuntimeVerified || !validRequest(request) {
		return nil, ErrChanged
	}
	if _, err := time.Parse(time.RFC3339Nano, result.RecordedAt); err != nil {
		return nil, ErrChanged
	}
	switch result.Status {
	case "installed_unverified", "rolled_back", "recovery_required":
	default:
		return nil, ErrChanged
	}
	return &result, nil
}

// Apply requires explicit confirmation of an unexpired signed preview. The
// caller holds the state writer lock; this package serializes local operations.
func (s *Store) Apply(ctx context.Context, r ApplyRequest) (*Operation, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if r.SchemaVersion != "local-skill-install-apply/v1" || !r.ConfirmInstall || !planID.MatchString(r.PlanID) || !signaturePattern.MatchString(r.PlanSignature) {
		return nil, ErrInvalid
	}
	select {
	case stageSlot <- struct{}{}:
		defer func() { <-stageSlot }()
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	if err := s.updateReplacementReserved(r.PlanID); err != nil {
		return nil, err
	}
	return s.apply(ctx, r)
}

func (s *Store) apply(ctx context.Context, r ApplyRequest) (*Operation, error) {
	p, err := s.readPlan(r.PlanID)
	if err != nil {
		return nil, err
	}
	if p.Signature != r.PlanSignature || p.ActorID != r.ActorID {
		return nil, ErrChanged
	}
	id := installID(p.PlanID)
	if _, err := os.Lstat(s.operationPath(id, "claim")); err == nil {
		return s.ReadOperation(ctx, id)
	} else if !os.IsNotExist(err) {
		return nil, ErrUnavailable
	}
	p, err = s.Load(ctx, p.PlanID)
	if err != nil {
		return nil, err
	}
	snapshot, err := s.imports.OpenInstallationSnapshot(ctx, p.Source.ImportID)
	if err != nil {
		return nil, sourceError(ctx, err)
	}
	metadata := snapshot.Metadata()
	c := Claim{SchemaVersion: "local-skill-install-claim/v1", InstallID: id, Plan: *p, Directories: metadata.Directories, Files: metadata.Files, ActorID: r.ActorID, CreatedAt: s.now().UTC().Format(time.RFC3339Nano)}
	for _, file := range c.Files {
		if reservedMetadata(file.Path) {
			return nil, ErrReservedMetadata
		}
	}
	for _, dir := range c.Directories {
		if reservedMetadata(dir) {
			return nil, ErrReservedMetadata
		}
	}
	if !manifestValid(c) || metadata.ArtifactDigest != p.Source.ArtifactDigest || metadata.AnalysisSHA256 != p.Source.AnalysisSHA256 {
		return nil, ErrChanged
	}
	doc, err := document(c, false)
	if err != nil {
		return nil, ErrUnavailable
	}
	c.Signature, err = s.key.SignCanonical(doc)
	if err != nil {
		return nil, ErrUnavailable
	}
	if err := s.operationCapacity(); err != nil {
		return nil, err
	}
	if err := publishDocument(s.operationPath(id, "claim"), c); err != nil {
		return nil, err
	}
	err = s.publishTarget(ctx, &c, snapshot)
	if err == nil {
		if boundaryErr := s.boundary("before_result"); boundaryErr != nil {
			err = ErrUnavailable
		} else {
			if err = s.checkAuthority(ctx, *p, true); err == nil {
				if _, err = s.verifyTarget(ctx, &c, true); err == nil {
					if err = s.checkAuthority(ctx, *p, false); err == nil {
						return s.end(&c, "installed_unverified", r.ActorID, "result")
					}
				}
			}
		}
	}
	cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	status := "rolled_back"
	if recoveryErr := s.rollbackTarget(cleanup, &c); recoveryErr != nil {
		status = "recovery_required"
	}
	result, endErr := s.end(&c, status, r.ActorID, "result")
	if endErr != nil {
		return nil, endErr
	}
	return result, err
}

// Recover only removes verified, unchanged objects belonging to a failed
// operation. It does not depend on the source or Grant still being usable.
func (s *Store) Recover(ctx context.Context, id, actor string) (*Operation, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	select {
	case stageSlot <- struct{}{}:
		defer func() { <-stageSlot }()
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	return s.recover(ctx, id, actor)
}

func (s *Store) recover(ctx context.Context, id, actor string) (*Operation, error) {
	c, err := s.claim(ctx, id)
	if err != nil {
		return nil, err
	}
	request := c.Plan.request()
	request.ActorID = actor
	if !validRequest(request) {
		return nil, ErrInvalid
	}
	current, err := s.ReadOperation(ctx, id)
	if err == nil && current.Status == "installed_unverified" {
		return nil, ErrConflict
	}
	if err == nil && current.Status == "rolled_back" {
		return current, nil
	}
	if err != nil && !errors.Is(err, ErrRecoveryRequired) {
		return nil, err
	}
	if err := s.rollbackTarget(ctx, c); err != nil {
		return nil, ErrRecoveryRequired
	}
	return s.end(c, "rolled_back", actor, "recovered")
}

func (s *Store) operationCapacity() error {
	parent := filepath.Join(s.dir, "operations")
	if err := checkDirectories(parent); err != nil {
		return err
	}
	f, err := os.Open(parent)
	if err != nil {
		return ErrUnavailable
	}
	names, err := f.Readdirnames(257)
	f.Close()
	if err != nil && err != io.EOF {
		return ErrUnavailable
	}
	if len(names) > 256 {
		return ErrLimit
	}
	count := 0
	for _, name := range names {
		if strings.HasSuffix(name, ".claim.json") {
			count++
		}
	}
	if count >= 64 {
		return ErrLimit
	}
	return nil
}

// View projects verified historical evidence without re-authorizing the plan.
// A missing final record is a recovery requirement, never a signed success.
type View struct {
	SchemaVersion  string     `json:"schema_version"`
	InstallID      string     `json:"install_id"`
	Plan           Plan       `json:"plan"`
	ClaimSignature string     `json:"claim_signature"`
	Status         string     `json:"status"`
	Operation      *Operation `json:"operation"`
}

func (s *Store) ReadView(ctx context.Context, id string) (*View, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	c, err := s.claim(ctx, id)
	if err != nil {
		return nil, err
	}
	result, err := s.ReadOperation(ctx, id)
	if err != nil && !errors.Is(err, ErrRecoveryRequired) {
		return nil, err
	}
	v := &View{SchemaVersion: "local-skill-install-view/v1", InstallID: id, Plan: c.Plan, ClaimSignature: c.Signature, Status: "recovery_required", Operation: result}
	if result != nil {
		v.Status = result.Status
	}
	return v, nil
}
