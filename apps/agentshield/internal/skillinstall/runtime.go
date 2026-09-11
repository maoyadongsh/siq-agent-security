package skillinstall

import (
	"context"
	"errors"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/importsource"
	"siq-agent-security/apps/agentshield/internal/state"
)

// Serialize full content rechecks; callers bound queueing with their context.
var runtimeValidationSlot = make(chan struct{}, 1)

var ErrNoTools = errors.New("skill_install_no_tools")

type ActivateRequest struct {
	SchemaVersion        string `json:"schema_version"`
	OperationSignature   string `json:"operation_signature"`
	ExpectedRevision     int    `json:"expected_revision"`
	ActorID              string `json:"actor_id"`
	ConfirmInstanceScope bool   `json:"confirm_instance_scope"`
}
type RuntimeBinding struct {
	SchemaVersion      string              `json:"schema_version"`
	BindingID          string              `json:"binding_id"`
	InstallID          string              `json:"install_id"`
	PlanSignature      string              `json:"plan_signature"`
	OperationSignature string              `json:"operation_signature"`
	GrantID            string              `json:"grant_id"`
	ApprovedRevision   int                 `json:"approved_revision"`
	ApprovedSignature  string              `json:"approved_signature"`
	PermissionDigest   string              `json:"permission_digest"`
	InstanceID         string              `json:"instance_id"`
	Source             importsource.Source `json:"source"`
	ActorID            string              `json:"actor_id"`
	CreatedAt          string              `json:"created_at"`
	Signature          string              `json:"signature"`
}
type Activated struct {
	SchemaVersion   string         `json:"schema_version"`
	Binding         RuntimeBinding `json:"binding"`
	GrantID         string         `json:"grant_id"`
	StateRevision   int            `json:"state_revision"`
	RuntimeVerified bool           `json:"runtime_verified"`
}

func bindingID(grantID string) string { return "sab-" + hash([]byte(grantID)) }
func (s *Store) bindingPath(id string) string {
	return filepath.Join(s.dir, "runtime-bindings", bindingID(id)+".json")
}
func (s *Store) runtimeBinding(ctx context.Context, id string) (*RuntimeBinding, error) {
	var b RuntimeBinding
	if len(id) == 0 || len(id) > 256 {
		return nil, ErrInvalid
	}
	if err := s.readSigned(ctx, s.bindingPath(id), &b); err != nil {
		return nil, err
	}
	if b.SchemaVersion != "local-skill-install-runtime-binding/v1" || b.BindingID != bindingID(id) || b.GrantID != id || !validInstallID(b.InstallID) || !signaturePattern.MatchString(b.PlanSignature) || !signaturePattern.MatchString(b.OperationSignature) || !signaturePattern.MatchString(b.ApprovedSignature) || !digestPattern.MatchString(b.PermissionDigest) || !instanceID.MatchString(b.InstanceID) || b.ApprovedRevision < 0 {
		return nil, ErrChanged
	}
	if _, err := b.Source.Canonical(); err != nil {
		return nil, ErrChanged
	}
	if _, err := time.Parse(time.RFC3339Nano, b.CreatedAt); err != nil {
		return nil, ErrChanged
	}
	return &b, nil
}

// bindingContent rechecks the complete target and imported source. It never
// uses the old preview TTL to extend or shorten the independent Grant lifetime.
func (s *Store) bindingContent(ctx context.Context, b *RuntimeBinding, g *grant.Grant) error {
	if g == nil || !grant.Verify(s.key.Public(), *g) || grant.ValidateLifetime(*g, s.now()) != nil || g.GrantID != b.GrantID || g.Platform != "hermes" || g.Subject.Type != "agent_instance" || g.Subject.ID != "hri-"+strings.TrimPrefix(b.InstanceID, "hi-") {
		return ErrChanged
	}
	digest, err := grant.PermissionDigest(*g)
	if err != nil || digest != b.PermissionDigest {
		return ErrChanged
	}
	adm, err := s.authority.GetAdmission(g.AdmissionID)
	if err != nil {
		return ErrChanged
	}
	source, err := importsource.Parse(*adm)
	if err != nil || source != b.Source {
		return ErrChanged
	}
	if err := s.imports.ValidatePermissionAdmission(ctx, *adm); err != nil {
		return sourceError(ctx, err)
	}
	v, err := s.ReadView(ctx, b.InstallID)
	if err != nil {
		return err
	}
	p := v.Plan
	request := p.request()
	request.ActorID = b.ActorID
	if !validRequest(request) || v.Status != "installed_unverified" || v.Operation == nil || v.Operation.Signature != b.OperationSignature || p.Signature != b.PlanSignature || p.GrantID != b.GrantID || p.GrantRevision != b.ApprovedRevision || p.GrantSignature != b.ApprovedSignature || p.GrantPermissionDigest != b.PermissionDigest || p.InstanceID != b.InstanceID || p.Source != b.Source {
		return ErrChanged
	}
	return ctx.Err()
}

// ValidateRuntimeGrant is called for every selected runtime reference. No
// successful validation is cached; raw management reads do not use this path.
func (s *Store) ValidateRuntimeGrant(ctx context.Context, g *grant.Grant) error {
	if ctx == nil {
		ctx = context.Background()
	}
	select {
	case runtimeValidationSlot <- struct{}{}:
		defer func() { <-runtimeValidationSlot }()
	case <-ctx.Done():
		return ctx.Err()
	}
	if g == nil || g.Status != "approved" {
		return ErrChanged
	}
	if !hasRuntimeTools(g) {
		return ErrNoTools
	}
	b, err := s.runtimeBinding(ctx, g.GrantID)
	if err != nil {
		return err
	}
	if err := s.removalStarted(b.InstallID); err != nil {
		return err
	}
	if err := s.bindingContent(ctx, b, g); err != nil {
		return err
	}
	current, revision, err := s.authority.GetGrantWithSeq(g.GrantID)
	if err != nil || revision != b.ApprovedRevision+1 || current.Signature != g.Signature || current.Status != "approved" {
		return ErrChanged
	}
	return ctx.Err()
}

// Activate prepares instance-scoped runtime permission, not verified Skill
// attribution. Binding publication precedes audited Grant publication.
func (s *Store) Activate(ctx context.Context, id string, req ActivateRequest) (*Activated, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if req.SchemaVersion != "local-skill-install-activate/v1" || !req.ConfirmInstanceScope || req.ExpectedRevision < 0 || !signaturePattern.MatchString(req.OperationSignature) {
		return nil, ErrInvalid
	}
	select {
	case stageSlot <- struct{}{}:
		defer func() { <-stageSlot }()
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	if err := s.removalStarted(id); err != nil {
		return nil, err
	}
	v, err := s.ReadView(ctx, id)
	if err != nil {
		return nil, err
	}
	if v.Status != "installed_unverified" || v.Operation == nil || v.Operation.Signature != req.OperationSignature {
		return nil, ErrChanged
	}
	p := v.Plan
	request := p.request()
	request.ActorID = req.ActorID
	if !validRequest(request) {
		return nil, ErrInvalid
	}
	if req.ExpectedRevision != p.GrantRevision {
		return nil, ErrChanged
	}
	if err := s.pendingGrantRemoval(ctx, p.GrantID); err != nil {
		return nil, err
	}
	g, revision, err := s.authority.GetGrantWithSeq(p.GrantID)
	if err != nil {
		return nil, ErrChanged
	}
	if !hasRuntimeTools(g) {
		return nil, ErrNoTools
	}
	b, err := s.runtimeBinding(ctx, p.GrantID)
	if err != nil && !errors.Is(err, ErrNotFound) {
		return nil, err
	}
	if b != nil && (b.InstallID != id || b.ActorID != req.ActorID || b.OperationSignature != req.OperationSignature || b.ApprovedRevision != req.ExpectedRevision) {
		return nil, ErrConflict
	}
	result := func() *Activated {
		return &Activated{SchemaVersion: "local-skill-install-activated/v1", Binding: *b, GrantID: p.GrantID, StateRevision: revision}
	}
	if g.Status == "approved" && b != nil && revision == b.ApprovedRevision+1 {
		if err := s.ValidateRuntimeGrant(ctx, g); err != nil {
			return nil, err
		}
		return result(), nil
	}
	if revision != p.GrantRevision || g.Status != "approved" || g.Signature != p.GrantSignature {
		return nil, ErrChanged
	}
	if b == nil {
		b = s.prospectiveBinding(v, req.ActorID)
		if err := s.bindingContent(ctx, b, g); err != nil {
			return nil, err
		}
		doc, err := document(b, false)
		if err != nil {
			return nil, ErrUnavailable
		}
		b.Signature, err = s.key.SignCanonical(doc)
		if err != nil {
			return nil, ErrUnavailable
		}
		if err := publishDocument(s.bindingPath(p.GrantID), b); err != nil {
			return nil, err
		}
	}
	if err := s.boundary("runtime_binding_published"); err != nil {
		return nil, ErrUnavailable
	}
	if err := s.bindingContent(ctx, b, g); err != nil {
		return nil, err
	}
	// Retain approved in the legacy Grant document. Old readers reject it for
	// runtime use; only the new verified binding path can select this version.
	if !grant.Verify(s.key.Public(), *g) || grant.ValidateLifetime(*g, s.now()) != nil {
		return nil, ErrChanged
	}
	revision, err = s.authority.CommitGrant(state.GrantCommit{Grant: *g, ExpectedRevision: p.GrantRevision, Audit: &state.AuditEvent{At: b.CreatedAt, Event: "skill_install_instance_permission", Target: p.GrantID, ActorID: b.ActorID, Note: "binding=" + b.BindingID + " install=" + id}})
	if err != nil {
		return nil, ErrUnavailable
	}
	if err := s.ValidateRuntimeGrant(ctx, g); err != nil {
		return nil, err
	}
	return result(), nil
}

func hasRuntimeTools(g *grant.Grant) bool {
	allow, approval := grant.RuntimeToolSets(g)
	return len(allow)+len(approval) > 0
}

func (s *Store) prospectiveBinding(v *View, actor string) *RuntimeBinding {
	p := v.Plan
	return &RuntimeBinding{SchemaVersion: "local-skill-install-runtime-binding/v1", BindingID: bindingID(p.GrantID), InstallID: v.InstallID, PlanSignature: p.Signature, OperationSignature: v.Operation.Signature, GrantID: p.GrantID, ApprovedRevision: p.GrantRevision, ApprovedSignature: p.GrantSignature, PermissionDigest: p.GrantPermissionDigest, InstanceID: p.InstanceID, Source: p.Source, ActorID: actor, CreatedAt: s.now().UTC().Format(time.RFC3339Nano)}
}

type RuntimeReadiness struct {
	SchemaVersion string          `json:"schema_version"`
	InstallID     string          `json:"install_id"`
	Grant         *grant.Grant    `json:"grant"`
	StateRevision int             `json:"state_revision"`
	Status        string          `json:"status"`
	Binding       *RuntimeBinding `json:"binding"`
}

// ReadReadiness never publishes a binding or a Grant revision. A response lost
// after Activate is recovered through this read, not an implicit write retry.
func (s *Store) ReadReadiness(ctx context.Context, id string) (*RuntimeReadiness, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	select {
	case stageSlot <- struct{}{}:
		defer func() { <-stageSlot }()
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	if err := s.removalStarted(id); err != nil {
		return nil, err
	}
	v, err := s.ReadView(ctx, id)
	if err != nil {
		return nil, err
	}
	if v.Status != "installed_unverified" || v.Operation == nil {
		return nil, ErrChanged
	}
	p := v.Plan
	g, revision, err := s.authority.GetGrantWithSeq(p.GrantID)
	if err != nil || g.Status != "approved" || g.Signature != p.GrantSignature {
		return nil, ErrChanged
	}
	b, err := s.runtimeBinding(ctx, p.GrantID)
	if err != nil && !errors.Is(err, ErrNotFound) {
		return nil, err
	}
	status := "not_prepared"
	check := b
	if b == nil {
		if revision != p.GrantRevision {
			return nil, ErrChanged
		}
		check = s.prospectiveBinding(v, p.ActorID)
	} else {
		if b.InstallID != id {
			return nil, ErrConflict
		}
		switch revision {
		case b.ApprovedRevision:
			status = "incomplete"
		case b.ApprovedRevision + 1:
			status = "prepared"
		default:
			return nil, ErrChanged
		}
	}
	if err := s.bindingContent(ctx, check, g); err != nil {
		return nil, err
	}
	if !hasRuntimeTools(g) {
		status = "no_tools"
	}
	// Detect concurrent management changes after the potentially expensive full
	// source/target reads. Runtime issuance still independently validates again.
	current, currentRevision, err := s.authority.GetGrantWithSeq(p.GrantID)
	if err != nil || currentRevision != revision || current.Signature != g.Signature || current.Status != "approved" {
		return nil, ErrChanged
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return &RuntimeReadiness{"local-skill-install-runtime-readiness/v1", id, g, revision, status, b}, nil
}

func (s *Store) ReadGrantReadiness(ctx context.Context, grantID string) (*RuntimeReadiness, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	b, err := s.runtimeBinding(ctx, grantID)
	if err != nil {
		return nil, err
	}
	result, err := s.ReadReadiness(ctx, b.InstallID)
	if err != nil {
		return nil, err
	}
	if result.Grant.GrantID != grantID {
		return nil, ErrChanged
	}
	return result, nil
}
