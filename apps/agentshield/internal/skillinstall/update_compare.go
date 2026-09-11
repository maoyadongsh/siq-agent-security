package skillinstall

import (
	"context"
	"encoding/json"
	"sort"
	"strconv"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/importsource"
	"siq-agent-security/apps/agentshield/internal/skillimport"
)

type UpdateCompareRequest struct {
	SchemaVersion             string `json:"schema_version"`
	OperationSignature        string `json:"operation_signature"`
	CandidateGrantID          string `json:"candidate_grant_id"`
	ExpectedCandidateRevision int    `json:"expected_candidate_revision"`
}
type UpdateContent struct {
	Kind       string `json:"kind"`
	SHA256     string `json:"sha256"`
	Bytes      int64  `json:"bytes"`
	Executable bool   `json:"executable"`
}
type UpdateContentChange struct {
	PathDisplay string         `json:"path_display"`
	PathDigest  string         `json:"path_digest"`
	Before      *UpdateContent `json:"before"`
	After       *UpdateContent `json:"after"`
}
type UpdateRule struct {
	Domain     string             `json:"domain"`
	Action     string             `json:"action"`
	Resource   admission.Resource `json:"resource"`
	Effect     string             `json:"effect"`
	Conditions map[string]any     `json:"conditions"`
	State      string             `json:"state"`
}
type UpdatePermissionChange struct {
	Change string     `json:"change"`
	Rule   UpdateRule `json:"rule"`
}
type UpdateComparison struct {
	SchemaVersion              string                   `json:"schema_version"`
	Record                     Record                   `json:"record"`
	CandidateSource            importsource.Source      `json:"candidate_source"`
	PreviousGrant              grant.Grant              `json:"previous_grant"`
	PreviousRevision           int                      `json:"previous_revision"`
	CandidateGrant             grant.Grant              `json:"candidate_grant"`
	CandidateRevision          int                      `json:"candidate_revision"`
	CheckedAt                  string                   `json:"checked_at"`
	ComparisonBasis            string                   `json:"comparison_basis"`
	PlatformChanges            bool                     `json:"platform_changes"`
	RuntimeVerified            bool                     `json:"runtime_verified"`
	RequiresConfirmation       bool                     `json:"requires_confirmation"`
	ContentChanges             []UpdateContentChange    `json:"content_changes"`
	ContentChangesTotal        int                      `json:"content_changes_total"`
	ContentChangesTruncated    bool                     `json:"content_changes_truncated"`
	PermissionChanges          []UpdatePermissionChange `json:"permission_changes"`
	PermissionChangesTotal     int                      `json:"permission_changes_total"`
	PermissionChangesTruncated bool                     `json:"permission_changes_truncated"`
	SettingsChanged            []string                 `json:"settings_changed"`
}

func updateTree(dirs []string, files []skillimport.File) map[string]UpdateContent {
	tree := make(map[string]UpdateContent, len(dirs)+len(files))
	for _, dir := range dirs {
		tree[dir] = UpdateContent{Kind: "directory"}
	}
	for _, f := range files {
		tree[f.Path] = UpdateContent{"file", f.SHA256, f.Bytes, f.Executable}
	}
	return tree
}
func (v *UpdateComparison) compareContents(before, after map[string]UpdateContent) {
	paths := make(map[string]bool, len(before)+len(after))
	for p := range before {
		paths[p] = true
	}
	for p := range after {
		paths[p] = true
	}
	keys := make([]string, 0, len(paths))
	for p := range paths {
		keys = append(keys, p)
	}
	sort.Strings(keys)
	for _, p := range keys {
		b, bok := before[p]
		a, aok := after[p]
		if bok && aok && b == a {
			continue
		}
		v.ContentChangesTotal++
		if len(v.ContentChanges) >= maxInspectionChanges {
			v.ContentChangesTruncated = true
			continue
		}
		display := strconv.QuoteToGraphic(p)
		display = display[1 : len(display)-1]
		runes := []rune(display)
		if len(runes) > 1024 {
			display = string(runes[:1023]) + "…"
		}
		change := UpdateContentChange{PathDisplay: display, PathDigest: hash([]byte(p))}
		if bok {
			value := b
			change.Before = &value
		}
		if aok {
			value := a
			change.After = &value
		}
		v.ContentChanges = append(v.ContentChanges, change)
	}
}
func updateCanonical(value any) (string, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	decoded, err := canon.Decode(raw)
	if err != nil {
		return "", err
	}
	normalized, err := canon.Marshal(decoded)
	return string(normalized), err
}
func updateRules(g grant.Grant) (map[string]UpdateRule, error) {
	rules := make(map[string]UpdateRule, len(g.Facts))
	for _, f := range g.Facts {
		r := UpdateRule{f.Domain, f.Action, f.Resource, f.Effect, f.Conditions, f.State}
		key, err := updateCanonical(r)
		if err != nil {
			return nil, err
		}
		rules[key] = r
	}
	return rules, nil
}
func (v *UpdateComparison) comparePermissions() error {
	before, err := updateRules(v.PreviousGrant)
	if err != nil {
		return err
	}
	after, err := updateRules(v.CandidateGrant)
	if err != nil {
		return err
	}
	keys := make([]string, 0, len(before)+len(after))
	for k := range before {
		keys = append(keys, k)
	}
	for k := range after {
		if _, ok := before[k]; !ok {
			keys = append(keys, k)
		}
	}
	sort.Strings(keys)
	for _, k := range keys {
		b, bok := before[k]
		a, aok := after[k]
		if bok && aok {
			continue
		}
		v.PermissionChangesTotal++
		if len(v.PermissionChanges) >= maxInspectionChanges {
			v.PermissionChangesTruncated = true
			continue
		}
		if bok {
			v.PermissionChanges = append(v.PermissionChanges, UpdatePermissionChange{"removed", b})
		} else {
			v.PermissionChanges = append(v.PermissionChanges, UpdatePermissionChange{"added", a})
		}
	}
	b, a := v.PreviousGrant, v.CandidateGrant
	for _, setting := range []struct {
		name          string
		before, after any
	}{
		{"default_effect", b.DefaultEffect, a.DefaultEffect}, {"enforcement_mode", b.EnforcementMode, a.EnforcementMode},
		{"expires_at", b.ExpiresAt, a.ExpiresAt}, {"hermes_toolset_allowlist", b.HermesToolsetAllowlist, a.HermesToolsetAllowlist},
		{"openclaw_tool_policy", b.OpenClawToolPolicy, a.OpenClawToolPolicy},
	} {
		left, e1 := updateCanonical(setting.before)
		right, e2 := updateCanonical(setting.after)
		if e1 != nil || e2 != nil {
			return ErrChanged
		}
		if left != right {
			v.SettingsChanged = append(v.SettingsChanged, setting.name)
		}
	}
	return nil
}
func (s *Store) CompareUpdate(ctx context.Context, id string, req UpdateCompareRequest) (*UpdateComparison, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if req.SchemaVersion != "local-skill-update-compare/v1" || !signaturePattern.MatchString(req.OperationSignature) || req.CandidateGrantID == "" || len(req.CandidateGrantID) > 256 || req.ExpectedCandidateRevision < 0 {
		return nil, ErrInvalid
	}
	select {
	case stageSlot <- struct{}{}:
		defer func() { <-stageSlot }()
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	return s.compareUpdate(ctx, id, req)
}
func (s *Store) compareUpdate(ctx context.Context, id string, req UpdateCompareRequest) (*UpdateComparison, error) {
	record, installed, err := s.historicalRecord(ctx, id)
	if err != nil {
		return nil, err
	}
	if record.RecordedStatus != "installed_unverified" || record.Operation == nil || record.Operation.Signature != req.OperationSignature {
		return nil, ErrChanged
	}
	if err := s.removalStarted(id); err != nil {
		return nil, err
	}
	old, oldRevision, _, _, err := s.removalAuthority(ctx, installed)
	if err != nil {
		return nil, err
	}
	next, nextRevision, err := s.authority.GetGrantWithSeq(req.CandidateGrantID)
	if err != nil || next == nil || nextRevision != req.ExpectedCandidateRevision || next.GrantID == old.GrantID || !grant.Verify(s.key.Public(), *next) || next.Platform != old.Platform || next.Subject != old.Subject || grant.ValidateLifetime(*next, s.now()) != nil {
		return nil, ErrChanged
	}
	if next.Status != "draft" && next.Status != "pending_approval" && next.Status != "approved" {
		return nil, ErrChanged
	}
	adm, err := s.authority.GetAdmission(next.AdmissionID)
	if err != nil {
		return nil, ErrChanged
	}
	if err := s.imports.ValidatePermissionAdmission(ctx, *adm); err != nil {
		return nil, sourceError(ctx, err)
	}
	source, err := importsource.Parse(*adm)
	if err != nil {
		return nil, ErrChanged
	}
	candidate, _, err := s.imports.Load(ctx, source.ImportID)
	if err != nil {
		return nil, sourceError(ctx, err)
	}
	if candidate.ArtifactDigest != source.ArtifactDigest || candidate.AnalysisSHA256 != source.AnalysisSHA256 {
		return nil, ErrChanged
	}
	out := &UpdateComparison{SchemaVersion: "local-skill-update-comparison/v1", Record: *record, CandidateSource: source, PreviousGrant: *old, PreviousRevision: oldRevision, CandidateGrant: *next, CandidateRevision: nextRevision, ComparisonBasis: "signed_installation_manifest", RequiresConfirmation: true, ContentChanges: []UpdateContentChange{}, PermissionChanges: []UpdatePermissionChange{}, SettingsChanged: []string{}}
	out.compareContents(updateTree(installed.Directories, installed.Files), updateTree(candidate.Directories, candidate.Files))
	if err := out.comparePermissions(); err != nil {
		return nil, ErrChanged
	}
	if err := s.boundary("update_compared"); err != nil {
		return nil, ErrUnavailable
	}
	currentCandidate, _, err := s.imports.Load(ctx, source.ImportID)
	if err != nil {
		return nil, sourceError(ctx, err)
	}
	if currentCandidate.Signature != candidate.Signature {
		return nil, ErrChanged
	}
	// Refresh both authority references after the potentially expensive content checks.
	for _, check := range []struct {
		g        *grant.Grant
		revision int
	}{{old, oldRevision}, {next, nextRevision}} {
		current, revision, err := s.authority.GetGrantWithSeq(check.g.GrantID)
		if err != nil || current == nil || revision != check.revision || current.Signature != check.g.Signature || !grant.Verify(s.key.Public(), *current) {
			return nil, ErrChanged
		}
	}
	if grant.ValidateLifetime(*next, s.now()) != nil {
		return nil, ErrChanged
	}
	if err := s.removalStarted(id); err != nil {
		return nil, err
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	out.CheckedAt = s.now().UTC().Format(time.RFC3339Nano)
	return out, nil
}
