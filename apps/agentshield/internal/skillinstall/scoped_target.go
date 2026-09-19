package skillinstall

import (
	"context"
	"os"
	"path/filepath"
	"strings"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/runtimepath"
)

const planV2 = "local-skill-install-plan/v2"
const scopedFilesystemProfile = "windows-local-drive/v1"

// TargetRef is signed installation location evidence, not runtime authority.
type TargetRef struct {
	TargetID                     string `json:"target_id"`
	Scope                        string `json:"scope"`
	FilesystemProfile            string `json:"filesystem_profile"`
	RootLocatorDigest            string `json:"root_locator_digest"`
	RootIdentityDigest           string `json:"root_identity_digest"`
	ConfigRootIdentityDigest     string `json:"config_root_identity_digest"`
	ExistingParentRelativePath   string `json:"existing_parent_relative_path"`
	ExistingParentIdentityDigest string `json:"existing_parent_identity_digest"`
}

// ScopedTarget keeps the host identity separate from an installation root.
// Resolvers enumerate server-owned roots; requests never supply these paths.
type ScopedTarget struct {
	Instance    Target
	ScopeRoot   string
	RootDisplay string
	Reference   TargetRef
}

type TargetResolverV2 func(context.Context, string, string) (ScopedTarget, error)

// ScopedTargetID is lexical only. Discovery may use it to identify an
// unavailable registered target, never as proof of a usable directory.
func ScopedTargetID(instance, scope, root string) (string, error) {
	if !instanceID.MatchString(instance) || len(scopeParents(scope)) == 0 {
		return "", ErrInvalid
	}
	canonical, err := runtimeaction.NormalizeResourceForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, "filesystem", root)
	if err != nil {
		return "", ErrChanged
	}
	raw, err := canon.Marshal(map[string]any{"domain": "workbuddy-skill-target/v1", "instance_id": instance, "scope": scope, "root_locator_digest": hash([]byte(canonical))})
	if err != nil {
		return "", ErrChanged
	}
	return "sit-" + hash(raw), nil
}

func (r TargetRef) valid() bool {
	if !strings.HasPrefix(r.TargetID, "sit-") || !digestPattern.MatchString(strings.TrimPrefix(r.TargetID, "sit-")) ||
		r.FilesystemProfile != scopedFilesystemProfile ||
		!digestPattern.MatchString(r.RootLocatorDigest) || !digestPattern.MatchString(r.RootIdentityDigest) ||
		!digestPattern.MatchString(r.ConfigRootIdentityDigest) || !digestPattern.MatchString(r.ExistingParentIdentityDigest) {
		return false
	}
	if r.ExistingParentRelativePath == "" && r.ExistingParentIdentityDigest != r.RootIdentityDigest ||
		r.Scope == "user" && r.RootIdentityDigest != r.ConfigRootIdentityDigest {
		return false
	}
	for _, rel := range scopeParents(r.Scope) {
		if r.ExistingParentRelativePath == rel {
			return true
		}
	}
	return false
}

func scopeParents(scope string) []string {
	switch scope {
	case "user":
		return []string{"", "skills"}
	case "project":
		return []string{"", ".codebuddy", ".codebuddy/skills"}
	default:
		return nil
	}
}

func scopeSkills(scope string) string {
	parents := scopeParents(scope)
	if len(parents) == 0 {
		return ""
	}
	return parents[len(parents)-1]
}

func nativeDirectory(path string) (*runtimepath.Snapshot, string, error) {
	snapshot, err := runtimepath.InspectWindows(path, false)
	if err != nil || !snapshot.IsDirectory() {
		return nil, "", ErrChanged
	}
	digest, err := snapshot.IdentityDigest()
	if err != nil {
		return nil, "", ErrChanged
	}
	return snapshot, digest, nil
}

// InspectScopedTarget is shared by discovery and the resolver. Its result must
// be recomputed at use; no cached discovery result authorizes a write.
func InspectScopedTarget(ctx context.Context, instance Target, scope, scopeRoot, rootDisplay string) (ScopedTarget, error) {
	var out ScopedTarget
	if err := ctx.Err(); err != nil {
		return out, err
	}
	if instance.Platform != "workbuddy" || !instanceID.MatchString(instance.InstanceID) ||
		!displayValid(instance.Display) || !displayValid(rootDisplay) || len(scopeParents(scope)) == 0 {
		return out, ErrChanged
	}
	config, configDigest, err := nativeDirectory(instance.Root)
	if err != nil {
		return out, err
	}
	root, rootDigest, err := nativeDirectory(scopeRoot)
	if err != nil || scope == "user" && (root.Path() != config.Path() || rootDigest != configDigest) {
		return out, ErrChanged
	}
	ref := TargetRef{Scope: scope, FilesystemProfile: scopedFilesystemProfile,
		RootLocatorDigest: hash([]byte(root.Path())), RootIdentityDigest: rootDigest,
		ConfigRootIdentityDigest: configDigest, ExistingParentIdentityDigest: rootDigest}
	lastParent := root
	for _, rel := range scopeParents(scope)[1:] {
		path := filepath.Join(scopeRoot, filepath.FromSlash(rel))
		if _, err := os.Lstat(path); os.IsNotExist(err) {
			break
		} else if err != nil {
			return out, ErrChanged
		}
		parent, digest, err := nativeDirectory(path)
		if err != nil {
			return out, err
		}
		ancestor, err := parent.AncestorIdentityDigest(root.Path())
		if err != nil || ancestor != rootDigest {
			return out, ErrChanged
		}
		ref.ExistingParentRelativePath, ref.ExistingParentIdentityDigest = rel, digest
		lastParent = parent
	}
	id, err := ScopedTargetID(instance.InstanceID, scope, root.Path())
	if err != nil || root.Revalidate() != nil || config.Revalidate() != nil || lastParent.Revalidate() != nil {
		return out, ErrChanged
	}
	ref.TargetID = id
	out = ScopedTarget{Instance: instance, ScopeRoot: scopeRoot, RootDisplay: rootDisplay, Reference: ref}
	return out, ctx.Err()
}

func sameTargetRef(a, b *TargetRef) bool {
	return a == nil && b == nil || a != nil && b != nil && *a == *b
}

func (s *Store) inspectRequestTarget(ctx context.Context, r Request) (Target, *TargetRef, string, string, error) {
	if r.SchemaVersion == "local-skill-install-stage-create/v1" {
		target, err := s.resolve(ctx, r.InstanceID)
		if err != nil || target.InstanceID != r.InstanceID || !supportedPlatform(target.Platform) || !displayValid(target.Display) {
			return Target{}, nil, "", "", ErrChanged
		}
		path, err := targetPath(target, r.DirectoryName)
		return target, nil, path, strings.TrimSuffix(target.Display, "/") + "/skills/" + r.DirectoryName, err
	}
	target, err := s.scopedTarget(ctx, r.InstanceID, r.TargetID)
	if err != nil {
		return Target{}, nil, "", "", err
	}
	path, err := vacantTarget(filepath.Join(target.ScopeRoot, filepath.FromSlash(scopeSkills(target.Reference.Scope))), r.DirectoryName)
	if err != nil {
		return Target{}, nil, "", "", err
	}
	canonical, err := runtimeaction.NormalizeResourceForProfile(runtimeaction.FilesystemProfile(target.Reference.FilesystemProfile), "filesystem", path)
	if err != nil {
		return Target{}, nil, "", "", ErrInvalid
	}
	return target.Instance, &target.Reference, canonical, strings.TrimSuffix(target.RootDisplay, "/") + "/" + scopeSkills(target.Reference.Scope) + "/" + r.DirectoryName, err
}

func (p Plan) wireVersion(base string) string {
	if p.SchemaVersion == planV2 {
		return base + "/v2"
	}
	return base + "/v1"
}

func validPlanTarget(p Plan) bool {
	switch p.SchemaVersion {
	case "local-skill-install-plan/v1":
		return p.TargetRef == nil && supportedPlatform(p.Platform)
	case planV2:
		if p.Platform != "workbuddy" || !instanceID.MatchString(p.InstanceID) || p.TargetRef == nil || !p.TargetRef.valid() {
			return false
		}
		raw, err := canon.Marshal(map[string]any{"domain": "workbuddy-skill-target/v1", "instance_id": p.InstanceID, "scope": p.TargetRef.Scope, "root_locator_digest": p.TargetRef.RootLocatorDigest})
		return err == nil && p.TargetRef.TargetID == "sit-"+hash(raw)
	default:
		return false
	}
}

func planGrantProfile(p Plan, g *grant.Grant) bool {
	return p.SchemaVersion != planV2 || g != nil && g.SchemaVersion == "grant/v2" &&
		g.FilesystemProfile == scopedFilesystemProfile && grant.ValidateFilesystemProfile(*g) == nil
}

// ValidRecordVersion checks the version relationship after the store has
// verified the signed claim/plan. It does not replace signature or live checks.
func ValidRecordVersion(r *Record) bool {
	if r == nil {
		return false
	}
	if r.SchemaVersion == "local-skill-install-record/v1" {
		return r.Plan.TargetRef == nil && (r.Plan.SchemaVersion == "" || r.Plan.SchemaVersion == "local-skill-install-plan/v1") && supportedPlatform(r.Plan.Platform)
	}
	return r.SchemaVersion == "local-skill-install-record/v2" && r.Plan.SchemaVersion == planV2 && validPlanTarget(r.Plan)
}

func (s *Store) scopedTarget(ctx context.Context, instance, id string) (ScopedTarget, error) {
	if s.resolveV2 == nil {
		return ScopedTarget{}, ErrChanged
	}
	provided, err := s.resolveV2(ctx, instance, id)
	if err != nil || provided.Instance.InstanceID != instance || provided.Reference.TargetID != id {
		return ScopedTarget{}, ErrChanged
	}
	current, err := InspectScopedTarget(ctx, provided.Instance, provided.Reference.Scope, provided.ScopeRoot, provided.RootDisplay)
	if err != nil || current.Reference != provided.Reference {
		return ScopedTarget{}, ErrChanged
	}
	return current, nil
}

func (s *Store) resolvePlanTarget(ctx context.Context, p Plan) (string, string, error) {
	if !validPlanTarget(p) {
		return "", "", ErrChanged
	}
	if p.SchemaVersion != planV2 {
		return s.legacyDestination(ctx, p)
	}
	target, err := s.scopedTarget(ctx, p.InstanceID, p.TargetRef.TargetID)
	if err != nil {
		return "", "", err
	}
	// The signed pre-existing ancestor remains pinned even after this
	// transaction creates additional fixed parent components.
	ref, expected := target.Reference, *p.TargetRef
	ref.ExistingParentRelativePath = expected.ExistingParentRelativePath
	ref.ExistingParentIdentityDigest = expected.ExistingParentIdentityDigest
	if ref != expected {
		return "", "", ErrChanged
	}
	parent, digest, err := nativeDirectory(filepath.Join(target.ScopeRoot, filepath.FromSlash(expected.ExistingParentRelativePath)))
	if err != nil || digest != expected.ExistingParentIdentityDigest {
		return "", "", ErrChanged
	}
	root, err := parent.AncestorIdentityDigest(parentRootPath(target.ScopeRoot))
	if err != nil || root != expected.RootIdentityDigest {
		return "", "", ErrChanged
	}
	destination := filepath.Join(target.ScopeRoot, filepath.FromSlash(scopeSkills(expected.Scope)), p.DirectoryName)
	canonical, err := runtimeaction.NormalizeResourceForProfile(runtimeaction.FilesystemProfile(expected.FilesystemProfile), "filesystem", destination)
	if err != nil || hash([]byte(canonical)) != p.TargetLocatorDigest ||
		strings.TrimSuffix(target.RootDisplay, "/")+"/"+scopeSkills(expected.Scope)+"/"+p.DirectoryName != p.TargetDisplay {
		return "", "", ErrChanged
	}
	if err := s.checkCreatedParentFacts(ctx, p, target); err != nil {
		return "", "", err
	}
	if parent.Revalidate() != nil {
		return "", "", ErrChanged
	}
	return destination, filepath.Join(target.ScopeRoot, ".siq-agent-security-installs", installID(p.PlanID)), nil
}

func parentRootPath(path string) string {
	canonical, _ := runtimeaction.NormalizeResourceForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, "filesystem", path)
	return canonical
}

// Recheck immediately before each v2 host mutation. Content/owner evidence
// alone cannot authorize writing through a replaced ancestor directory.
func (s *Store) publicationTargetUnchanged(ctx context.Context, c *Claim, destination, pool string) error {
	if c.Plan.SchemaVersion != planV2 {
		return nil
	}
	current, currentPool, err := s.destination(ctx, c.Plan)
	if err != nil || current != destination || currentPool != pool {
		return ErrChanged
	}
	return nil
}
