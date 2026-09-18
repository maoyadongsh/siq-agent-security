package skillinstall

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"siq-agent-security/apps/agentshield/internal/statefs"
)

// parentFact only records a parent created by this v2 transaction. Existing
// directories are pinned by the preview, never adopted by writing a fact.
type parentFact struct {
	SchemaVersion  string `json:"schema_version"`
	InstallID      string `json:"install_id"`
	ClaimSignature string `json:"claim_signature"`
	RelativeParent string `json:"relative_parent"`
	IdentityDigest string `json:"identity_digest"`
	RecordedAt     string `json:"recorded_at"`
	Signature      string `json:"signature"`
}

func parentIndex(ref TargetRef) int {
	for i, rel := range scopeParents(ref.Scope) {
		if rel == ref.ExistingParentRelativePath {
			return i
		}
	}
	return -1
}

func parentFactPath(pool string, index int) string {
	return filepath.Join(pool, fmt.Sprintf("parent-%d.json", index))
}

func (s *Store) checkCreatedParentFacts(ctx context.Context, p Plan, target ScopedTarget) error {
	anchor := parentIndex(*p.TargetRef)
	if anchor < 0 {
		return ErrChanged
	}
	pool := filepath.Join(target.ScopeRoot, ".siq-agent-security-installs", installID(p.PlanID))
	var claim *Claim
	for i, rel := range scopeParents(p.TargetRef.Scope) {
		if i <= anchor {
			continue
		}
		path := filepath.Join(target.ScopeRoot, filepath.FromSlash(rel))
		if _, err := os.Lstat(path); os.IsNotExist(err) {
			// A previously published fact cannot silently disappear with its
			// directory and then authorize recreating that directory.
			if _, err := os.Lstat(parentFactPath(pool, i)); !os.IsNotExist(err) {
				return ErrChanged
			}
			continue
		} else if err != nil {
			return ErrChanged
		}
		if claim == nil {
			var err error
			claim, err = s.claim(ctx, installID(p.PlanID))
			if err != nil || !sameDocument(claim.Plan, p) {
				return ErrChanged
			}
		}
		var fact parentFact
		if err := s.readSigned(ctx, parentFactPath(pool, i), &fact); err != nil {
			return ErrChanged
		}
		recorded, e1 := time.Parse(time.RFC3339Nano, fact.RecordedAt)
		started, e2 := time.Parse(time.RFC3339Nano, claim.CreatedAt)
		if fact.SchemaVersion != "local-skill-install-parent-fact/v1" || fact.InstallID != claim.InstallID ||
			fact.ClaimSignature != claim.Signature || fact.RelativeParent != rel || !digestPattern.MatchString(fact.IdentityDigest) ||
			e1 != nil || e2 != nil || recorded.Before(started) {
			return ErrChanged
		}
		snapshot, digest, err := nativeDirectory(path)
		if err != nil || digest != fact.IdentityDigest || snapshot.Revalidate() != nil {
			return ErrChanged
		}
		if rel == target.Reference.ExistingParentRelativePath && digest != target.Reference.ExistingParentIdentityDigest {
			return ErrChanged
		}
	}
	return ctx.Err()
}

func (s *Store) createScopedParents(ctx context.Context, c *Claim, pool string) error {
	target, err := s.scopedTarget(ctx, c.Plan.InstanceID, c.Plan.TargetRef.TargetID)
	if err != nil {
		return err
	}
	if _, _, err := s.resolvePlanTarget(ctx, c.Plan); err != nil {
		return err
	}
	anchor := parentIndex(*c.Plan.TargetRef)
	for i, rel := range scopeParents(c.Plan.TargetRef.Scope) {
		if i <= anchor {
			continue
		}
		if err := ctx.Err(); err != nil {
			return err
		}
		path := filepath.Join(target.ScopeRoot, filepath.FromSlash(rel))
		// This function runs once after the exclusive claim/pool publication.
		// Existing unrecorded parents are never guessed to be ours.
		if err := s.checkCreatedParentFacts(ctx, c.Plan, target); err != nil {
			return err
		}
		if _, _, err := s.resolvePlanTarget(ctx, c.Plan); err != nil {
			return err
		}
		if _, err := os.Lstat(path); err == nil {
			continue // already accompanied by this claim's valid signed fact
		} else if !os.IsNotExist(err) {
			return ErrChanged
		}
		if err := statefs.Mkdir(path, 0700); err != nil {
			return ErrChanged
		}
		created, err := os.Lstat(path)
		if err != nil {
			return ErrChanged
		}
		if err := s.boundary("parent_created:" + rel); err != nil {
			return ErrUnavailable
		}
		snapshot, digest, err := nativeDirectory(path)
		current, statErr := os.Lstat(path)
		if err != nil || statErr != nil || !os.SameFile(created, current) || snapshot.Revalidate() != nil {
			return ErrChanged
		}
		ancestor, err := snapshot.AncestorIdentityDigest(parentRootPath(target.ScopeRoot))
		if err != nil || ancestor != c.Plan.TargetRef.RootIdentityDigest {
			return ErrChanged
		}
		fact := parentFact{SchemaVersion: "local-skill-install-parent-fact/v1", InstallID: c.InstallID,
			ClaimSignature: c.Signature, RelativeParent: rel, IdentityDigest: digest, RecordedAt: s.now().UTC().Format(time.RFC3339Nano)}
		doc, err := document(fact, false)
		if err != nil {
			return ErrUnavailable
		}
		fact.Signature, err = s.key.SignCanonical(doc)
		if err != nil || snapshot.Revalidate() != nil {
			return ErrChanged
		}
		if err := publishDocument(parentFactPath(pool, i), fact); err != nil {
			return err
		}
		if err := s.boundary("parent_fact_published:" + rel); err != nil {
			return ErrUnavailable
		}
	}
	return s.checkCreatedParentFacts(ctx, c.Plan, target)
}

// advancedTargetRef re-anchors an update only after the old installation and
// all old parent facts have been checked. It never changes a target or host.
func (s *Store) advancedTargetRef(ctx context.Context, p Plan) (*TargetRef, error) {
	if p.SchemaVersion != planV2 {
		return nil, nil
	}
	if _, _, err := s.resolvePlanTarget(ctx, p); err != nil {
		return nil, err
	}
	target, err := s.scopedTarget(ctx, p.InstanceID, p.TargetRef.TargetID)
	if err != nil {
		return nil, err
	}
	if err := s.checkCreatedParentFacts(ctx, p, target); err != nil {
		return nil, err
	}
	ref := target.Reference
	if parentIndex(ref) < parentIndex(*p.TargetRef) {
		return nil, ErrChanged
	}
	return &ref, nil
}

// Historical replacement validation is deliberately independent of live
// source files: an update/removal result must remain readable after cleanup.
func replacementAnchorValid(old, next Plan) bool {
	if old.TargetRef == nil || next.TargetRef == nil {
		return old.TargetRef == nil && next.TargetRef == nil
	}
	a, b := *old.TargetRef, *next.TargetRef
	if !a.valid() || !b.valid() || parentIndex(b) < parentIndex(a) {
		return false
	}
	if parentIndex(b) == parentIndex(a) {
		return a == b
	}
	b.ExistingParentRelativePath, b.ExistingParentIdentityDigest = a.ExistingParentRelativePath, a.ExistingParentIdentityDigest
	return a == b
}
