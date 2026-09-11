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
	"siq-agent-security/apps/agentshield/internal/state"
)

var ErrRemovalPending = errors.New("skill_install_removal_pending")

type RemoveRequest struct {
	SchemaVersion            string `json:"schema_version"`
	OperationSignature       string `json:"operation_signature"`
	ExpectedGrantRevision    int    `json:"expected_grant_revision"`
	ExpectedBindingSignature string `json:"expected_binding_signature"`
	ActorID                  string `json:"actor_id"`
	ConfirmRemove            bool   `json:"confirm_remove"`
}
type RemovalClaim struct {
	SchemaVersion              string `json:"schema_version"`
	InstallID                  string `json:"install_id"`
	InstallationClaimSignature string `json:"installation_claim_signature"`
	OperationSignature         string `json:"operation_signature"`
	GrantID                    string `json:"grant_id"`
	GrantRevision              int    `json:"grant_revision"`
	GrantSignature             string `json:"grant_signature"`
	BindingSignature           string `json:"binding_signature"`
	RetainedInstallID          string `json:"retained_install_id"`
	RevokeGrant                bool   `json:"revoke_grant"`
	ActorID                    string `json:"actor_id"`
	CreatedAt                  string `json:"created_at"`
	Signature                  string `json:"signature"`
}
type RemovalResult struct {
	SchemaVersion         string `json:"schema_version"`
	InstallID             string `json:"install_id"`
	RemovalClaimSignature string `json:"removal_claim_signature"`
	Status                string `json:"status"`
	GrantID               string `json:"grant_id"`
	GrantRevision         int    `json:"grant_revision"`
	GrantSignature        string `json:"grant_signature"`
	GrantRevoked          bool   `json:"grant_revoked"`
	RetainedInstallID     string `json:"retained_install_id"`
	ActorID               string `json:"actor_id"`
	RecordedAt            string `json:"recorded_at"`
	TargetAbsent          bool   `json:"target_absent"`
	Signature             string `json:"signature"`
}
type RemovalView struct {
	SchemaVersion     string         `json:"schema_version"`
	Record            Record         `json:"record"`
	Claim             *RemovalClaim  `json:"claim"`
	Result            *RemovalResult `json:"result"`
	Grant             *grant.Grant   `json:"grant"`
	StateRevision     *int           `json:"state_revision"`
	Status            string         `json:"status"`
	WillRevokeGrant   bool           `json:"will_revoke_grant"`
	RetainedInstallID string         `json:"retained_install_id"`
	BindingSignature  string         `json:"binding_signature"`
}

func (s *Store) removalPath(id, suffix string) string {
	return filepath.Join(s.dir, "removals", id+"."+suffix+".json")
}
func (s *Store) removalStarted(id string) error {
	if !validInstallID(id) {
		return ErrInvalid
	}
	if err := checkDirectories(filepath.Dir(s.removalPath(id, "claim"))); err != nil {
		return err
	}
	if _, err := os.Lstat(s.removalPath(id, "claim")); os.IsNotExist(err) {
		return nil
	} else if err != nil {
		return ErrUnavailable
	}
	return ErrRemovalPending
}
func (s *Store) readRemovalClaim(ctx context.Context, id string) (*RemovalClaim, error) {
	if !validInstallID(id) {
		return nil, ErrInvalid
	}
	var c RemovalClaim
	if err := s.readSigned(ctx, s.removalPath(id, "claim"), &c); err != nil {
		return nil, err
	}
	if c.SchemaVersion != "local-skill-install-removal-claim/v1" || c.InstallID != id || !signaturePattern.MatchString(c.InstallationClaimSignature) || !signaturePattern.MatchString(c.OperationSignature) || c.GrantID == "" || len(c.GrantID) > 256 || c.GrantRevision < 0 || !signaturePattern.MatchString(c.GrantSignature) || (c.BindingSignature != "" && !signaturePattern.MatchString(c.BindingSignature)) || (c.RevokeGrant && c.RetainedInstallID != "") || (!c.RevokeGrant && (!validInstallID(c.RetainedInstallID) || c.RetainedInstallID == id || c.BindingSignature == "")) {
		return nil, ErrChanged
	}
	if _, err := time.Parse(time.RFC3339Nano, c.CreatedAt); err != nil {
		return nil, ErrChanged
	}
	return &c, nil
}

// An interrupted removal must not allow Activate to move its pending Grant to
// a different installation. This bounded scan is management-only.
func (s *Store) pendingGrantRemoval(ctx context.Context, grantID string) error {
	dir := filepath.Join(s.dir, "removals")
	if err := checkDirectories(dir); err != nil {
		return err
	}
	f, err := os.Open(dir)
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
	for _, name := range names {
		if !strings.HasSuffix(name, ".claim.json") {
			continue
		}
		c, err := s.readRemovalClaim(ctx, strings.TrimSuffix(name, ".claim.json"))
		if err != nil {
			return err
		}
		if c.GrantID == grantID && c.RevokeGrant {
			return ErrRemovalPending
		}
	}
	return ctx.Err()
}
func (s *Store) removalAuthority(ctx context.Context, c *Claim) (*grant.Grant, int, string, string, error) {
	g, revision, err := s.authority.GetGrantWithSeq(c.Plan.GrantID)
	if err != nil || g == nil || !grant.Verify(s.key.Public(), *g) || (g.Status != "approved" && g.Status != "revoked") || g.Platform != "hermes" || g.Subject.Type != "agent_instance" || g.Subject.ID != "hri-"+strings.TrimPrefix(c.Plan.InstanceID, "hi-") {
		return nil, 0, "", "", ErrChanged
	}
	admissionID, err := c.Plan.Source.AdmissionID()
	if err != nil || admissionID != g.AdmissionID {
		return nil, 0, "", "", ErrChanged
	}
	digest, err := grant.PermissionDigest(*g)
	if err != nil || digest != c.Plan.GrantPermissionDigest {
		return nil, 0, "", "", ErrChanged
	}
	b, err := s.runtimeBinding(ctx, g.GrantID)
	if errors.Is(err, ErrNotFound) {
		return g, revision, "", "", nil
	}
	if err != nil {
		return nil, 0, "", "", err
	}
	if b.InstanceID != c.Plan.InstanceID || b.PermissionDigest != digest || b.Source != c.Plan.Source {
		return nil, 0, "", "", ErrChanged
	}
	retained := ""
	if b.InstallID != c.InstallID {
		retained = b.InstallID
	}
	return g, revision, b.Signature, retained, nil
}
func (s *Store) removalView(ctx context.Context, id string) (*RemovalView, *Claim, error) {
	record, installed, err := s.historicalRecord(ctx, id)
	if err != nil {
		return nil, nil, err
	}
	if record.RecordedStatus != "installed_unverified" || record.Operation == nil {
		return nil, nil, ErrConflict
	}
	v := &RemovalView{SchemaVersion: "local-skill-install-removal-view/v1", Record: *record, Status: "not_requested"}
	removal, err := s.readRemovalClaim(ctx, id)
	if err != nil && !errors.Is(err, ErrNotFound) {
		return nil, nil, err
	}
	if removal != nil {
		request := installed.Plan.request()
		request.ActorID = removal.ActorID
		if !validRequest(request) || removal.InstallationClaimSignature != installed.Signature || removal.OperationSignature != record.Operation.Signature || removal.GrantID != installed.Plan.GrantID {
			return nil, nil, ErrChanged
		}
		v.Claim = removal
		v.WillRevokeGrant = removal.RevokeGrant
		v.RetainedInstallID = removal.RetainedInstallID
		v.BindingSignature = removal.BindingSignature
		var result RemovalResult
		err := s.readSigned(ctx, s.removalPath(id, "result"), &result)
		if err == nil {
			if result.SchemaVersion != "local-skill-install-removal-result/v1" || result.InstallID != id || result.RemovalClaimSignature != removal.Signature || result.Status != "removed" || !result.TargetAbsent || result.GrantID != removal.GrantID || result.GrantRevision < removal.GrantRevision || !signaturePattern.MatchString(result.GrantSignature) || result.ActorID != removal.ActorID || result.RetainedInstallID != removal.RetainedInstallID || (removal.RevokeGrant && !result.GrantRevoked) {
				return nil, nil, ErrChanged
			}
			if _, err := time.Parse(time.RFC3339Nano, result.RecordedAt); err != nil {
				return nil, nil, ErrChanged
			}
			v.Result = &result
			v.Status = "removed"
			return v, installed, nil // Historical completion; never touch a reused path.
		}
		if !errors.Is(err, ErrNotFound) {
			return nil, nil, err
		}
	} else {
		if _, err := os.Lstat(s.removalPath(id, "result")); !os.IsNotExist(err) {
			return nil, nil, ErrChanged
		}
	}
	g, revision, binding, retained, err := s.removalAuthority(ctx, installed)
	if err != nil {
		return nil, nil, err
	}
	v.BindingSignature = binding
	v.Grant = g
	v.StateRevision = &revision
	if removal == nil {
		v.WillRevokeGrant = retained == ""
		v.RetainedInstallID = retained
		return v, installed, nil
	}
	if binding != removal.BindingSignature || retained != removal.RetainedInstallID {
		return nil, nil, ErrChanged
	}
	if removal.RevokeGrant && g.Status != "revoked" {
		if revision != removal.GrantRevision || g.Signature != removal.GrantSignature {
			return nil, nil, ErrChanged
		}
		v.Status = "revocation_pending"
	} else {
		v.Status = "cleanup_pending"
	}
	return v, installed, nil
}
func (s *Store) ReadRemoval(ctx context.Context, id string) (*RemovalView, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	v, _, err := s.removalView(ctx, id)
	return v, err
}
func (s *Store) Remove(ctx context.Context, id string, req RemoveRequest) (*RemovalView, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if req.SchemaVersion != "local-skill-install-remove/v1" || !req.ConfirmRemove || req.ExpectedGrantRevision < 0 || !signaturePattern.MatchString(req.OperationSignature) || (req.ExpectedBindingSignature != "" && !signaturePattern.MatchString(req.ExpectedBindingSignature)) {
		return nil, ErrInvalid
	}
	select {
	case stageSlot <- struct{}{}:
		defer func() { <-stageSlot }()
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	return s.remove(ctx, id, req)
}

func (s *Store) remove(ctx context.Context, id string, req RemoveRequest) (*RemovalView, error) {
	v, installed, err := s.removalView(ctx, id)
	if err != nil {
		return nil, err
	}
	request := installed.Plan.request()
	request.ActorID = req.ActorID
	if !validRequest(request) {
		return nil, ErrInvalid
	}
	if v.Record.Operation.Signature != req.OperationSignature {
		return nil, ErrChanged
	}
	if v.Claim != nil {
		c := v.Claim
		if c.ActorID != req.ActorID || c.GrantRevision != req.ExpectedGrantRevision || c.BindingSignature != req.ExpectedBindingSignature {
			return nil, ErrConflict
		}
		if v.Status == "removed" {
			return v, nil
		}
	} else {
		g, revision, binding, retained, err := s.removalAuthority(ctx, installed)
		if err != nil {
			return nil, err
		}
		if revision != req.ExpectedGrantRevision || binding != req.ExpectedBindingSignature {
			return nil, ErrChanged
		}
		c := &RemovalClaim{SchemaVersion: "local-skill-install-removal-claim/v1", InstallID: id, InstallationClaimSignature: installed.Signature, OperationSignature: req.OperationSignature, GrantID: g.GrantID, GrantRevision: revision, GrantSignature: g.Signature, BindingSignature: binding, RetainedInstallID: retained, RevokeGrant: retained == "", ActorID: req.ActorID, CreatedAt: s.now().UTC().Format(time.RFC3339Nano)}
		doc, err := document(c, false)
		if err != nil {
			return nil, ErrUnavailable
		}
		c.Signature, err = s.key.SignCanonical(doc)
		if err != nil {
			return nil, ErrUnavailable
		}
		if err := publishDocument(s.removalPath(id, "claim"), c); err != nil {
			return nil, err
		}
		v.Claim = c
	}
	if err := s.boundary("removal_claim_published"); err != nil {
		return nil, ErrUnavailable
	}
	v, _, err = s.removalView(ctx, id)
	if err != nil {
		return nil, err
	}
	if v.Status == "revocation_pending" {
		revoked, err := grant.Revoke(*v.Grant, s.key)
		if err != nil {
			return nil, ErrChanged
		}
		_, err = s.authority.CommitGrant(state.GrantCommit{Grant: revoked, ExpectedRevision: *v.StateRevision, Audit: &state.AuditEvent{At: v.Claim.CreatedAt, Event: "skill_install_remove_authority", Target: revoked.GrantID, ActorID: v.Claim.ActorID, Note: "install=" + id + " removal=" + hash([]byte(v.Claim.Signature))}})
		if err != nil {
			return nil, ErrUnavailable
		}
	}
	v, _, err = s.removalView(ctx, id)
	if err != nil {
		return nil, err
	}
	if v.Status != "cleanup_pending" {
		return nil, ErrChanged
	}
	if err := s.boundary("removal_authority_ready"); err != nil {
		return v, ErrUnavailable
	}
	if err := s.cleanupTarget(ctx, installed, "removal_"); err != nil {
		return v, ErrRecoveryRequired
	}
	destination, _, err := s.destination(ctx, installed.Plan)
	if err != nil {
		return v, ErrRecoveryRequired
	}
	if _, err := os.Lstat(destination); !os.IsNotExist(err) {
		return v, ErrRecoveryRequired
	}
	if err := ctx.Err(); err != nil {
		return v, err
	}
	if err := s.boundary("removal_before_result"); err != nil {
		return v, ErrUnavailable
	}
	v, _, err = s.removalView(ctx, id)
	if err != nil {
		return nil, err
	}
	if v.Status != "cleanup_pending" {
		return nil, ErrChanged
	}
	result := &RemovalResult{SchemaVersion: "local-skill-install-removal-result/v1", InstallID: id, RemovalClaimSignature: v.Claim.Signature, Status: "removed", GrantID: v.Grant.GrantID, GrantRevision: *v.StateRevision, GrantSignature: v.Grant.Signature, GrantRevoked: v.Grant.Status == "revoked", RetainedInstallID: v.Claim.RetainedInstallID, ActorID: v.Claim.ActorID, RecordedAt: s.now().UTC().Format(time.RFC3339Nano), TargetAbsent: true}
	doc, err := document(result, false)
	if err != nil {
		return v, ErrUnavailable
	}
	result.Signature, err = s.key.SignCanonical(doc)
	if err != nil {
		return v, ErrUnavailable
	}
	if err := publishDocument(s.removalPath(id, "result"), result); err != nil {
		return v, err
	}
	return s.ReadRemoval(ctx, id)
}
