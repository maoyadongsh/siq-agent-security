// Package skillinstall prepares content-bound installation transactions.
// Staging never changes platform files or activates runtime permission.
package skillinstall

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"math/rand"
	"os"
	"path/filepath"
	"regexp"
	"siq-agent-security/apps/agentshield/internal/statefs"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/importsource"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/state"
)

var (
	ErrInvalid     = errors.New("skill_install_invalid")
	ErrChanged     = errors.New("skill_install_changed")
	ErrConflict    = errors.New("skill_install_conflict")
	ErrExpired     = errors.New("skill_install_expired")
	ErrUnavailable = errors.New("skill_install_unavailable")
	ErrNotFound    = errors.New("skill_install_not_found")
	ErrLimit       = errors.New("skill_install_limit")
)
var stageSlot = make(chan struct{}, 1)
var requestID = regexp.MustCompile(`^is-[a-f0-9]{32}$`)
var planID = regexp.MustCompile(`^sip-[a-f0-9]{64}$`)
var instanceID = regexp.MustCompile(`^hi-[a-f0-9]{32}$`)
var namePattern = regexp.MustCompile(`^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$`)

const planTTL = 5 * time.Minute
const maxStages = 64

type Request struct {
	SchemaVersion    string `json:"schema_version"`
	RequestID        string `json:"request_id"`
	GrantID          string `json:"grant_id"`
	ExpectedRevision int    `json:"expected_revision"`
	InstanceID       string `json:"instance_id"`
	DirectoryName    string `json:"directory_name"`
	ActorID          string `json:"actor_id"`
	TargetID         string `json:"target_id,omitempty"`
}
type Target struct{ InstanceID, Platform, Root, Display string }

func supportedPlatform(platform string) bool {
	return platform == "hermes" || platform == "openclaw"
}

func subjectForInstance(id string) string {
	return "hri-" + strings.TrimPrefix(id, "hi-")
}

type Plan struct {
	SchemaVersion         string              `json:"schema_version"`
	PlanID                string              `json:"plan_id"`
	RequestID             string              `json:"request_id"`
	Source                importsource.Source `json:"source"`
	GrantID               string              `json:"grant_id"`
	GrantRevision         int                 `json:"grant_revision"`
	GrantSignature        string              `json:"grant_signature"`
	GrantPermissionDigest string              `json:"grant_permission_digest"`
	Platform              string              `json:"platform"`
	InstanceID            string              `json:"instance_id"`
	DirectoryName         string              `json:"directory_name"`
	TargetLocatorDigest   string              `json:"target_locator_digest"`
	TargetDisplay         string              `json:"target_display"`
	ActorID               string              `json:"actor_id"`
	CreatedAt             string              `json:"created_at"`
	ExpiresAt             string              `json:"expires_at"`
	FileCount             int                 `json:"file_count"`
	TotalBytes            int64               `json:"total_bytes"`
	Installed             bool                `json:"installed"`
	RuntimeVerified       bool                `json:"runtime_verified"`
	Signature             string              `json:"signature"`
	TargetRef             *TargetRef          `json:"target_ref,omitempty"`
}
type Store struct {
	dir       string
	key       *signing.Key
	imports   *skillimport.Store
	authority *state.Store
	resolve   func(context.Context, string) (Target, error)
	resolveV2 TargetResolverV2
	now       func() time.Time
	// Private test boundary, never set from runtime configuration.
	boundary func(string) error
	// Upstream re-fetch seam for update checks. The default re-fetches the
	// recorded import source; tests substitute a snapshot so cross-package
	// behavior is exercised without a network. Never set from runtime
	// configuration.
	upstream func(context.Context, *skillimport.Record, string) (*skillimport.UpstreamSnapshot, error)
	// Scheduling jitter seam for automatic update checks: given the check
	// interval it returns a non-negative spread added to the next due time so
	// a fleet of installs never fires in lockstep. Never set from runtime
	// configuration.
	jitter func(time.Duration) time.Duration
}

func Open(authority *state.Store, key *signing.Key, imports *skillimport.Store, resolve func(context.Context, string) (Target, error)) (*Store, error) {
	return OpenWithTargets(authority, key, imports, resolve, nil)
}

// OpenWithTargets preserves the legacy resolver and enables explicitly selected
// v2 scopes. A missing v2 resolver always rejects v2 operations.
func OpenWithTargets(authority *state.Store, key *signing.Key, imports *skillimport.Store, resolve func(context.Context, string) (Target, error), resolveV2 TargetResolverV2) (*Store, error) {
	if authority == nil || key == nil || imports == nil || resolve == nil {
		return nil, ErrInvalid
	}
	if err := statefs.CheckPrivateDir(authority.Dir); err != nil {
		return nil, ErrChanged
	}
	dir := filepath.Join(authority.Dir, "skill-installations")
	for _, path := range []string{dir, filepath.Join(dir, "plans"), filepath.Join(dir, "stages"), filepath.Join(dir, "operations"), filepath.Join(dir, "runtime-bindings"), filepath.Join(dir, "removals"), filepath.Join(dir, "update-plans"), filepath.Join(dir, "update-stages"), filepath.Join(dir, "update-operations"), filepath.Join(dir, "update-installations")} {
		if err := privateDirectory(path); err != nil {
			return nil, err
		}
	}
	return &Store{dir: dir, key: key, imports: imports, authority: authority, resolve: resolve, resolveV2: resolveV2, now: time.Now,
		boundary: func(string) error { return nil },
		jitter: func(d time.Duration) time.Duration {
			// Up to one eighth of the interval, drawn per write. math/rand's
			// global source is auto-seeded in Go 1.20+.
			spread := d / 8
			if spread <= 0 {
				return 0
			}
			return time.Duration(rand.Int63n(int64(spread) + 1))
		},
		upstream: func(ctx context.Context, record *skillimport.Record, remoteURL string) (*skillimport.UpstreamSnapshot, error) {
			return imports.CheckUpstream(ctx, record.ImportID, remoteURL)
		}}, nil
}
func nameValid(name string) bool {
	if !namePattern.MatchString(name) {
		return false
	}
	upper := strings.ToUpper(name)
	if upper == "CON" || upper == "PRN" || upper == "AUX" || upper == "NUL" {
		return false
	}
	return !((strings.HasPrefix(upper, "COM") || strings.HasPrefix(upper, "LPT")) && len(upper) == 4 && strings.ContainsRune("123456789", rune(upper[3])))
}
func validRequest(r Request) bool {
	version := r.SchemaVersion == "local-skill-install-stage-create/v1" && r.TargetID == "" || r.SchemaVersion == "local-skill-install-stage-create/v2" && strings.HasPrefix(r.TargetID, "sit-") && digestPattern.MatchString(strings.TrimPrefix(r.TargetID, "sit-"))
	return version && requestID.MatchString(r.RequestID) && r.GrantID != "" && len(r.GrantID) <= 256 && r.ExpectedRevision >= 0 && instanceID.MatchString(r.InstanceID) && nameValid(r.DirectoryName) &&
		r.ActorID != "" && strings.TrimSpace(r.ActorID) == r.ActorID && utf8.ValidString(r.ActorID) && utf8.RuneCountInString(r.ActorID) <= 128 && strings.IndexFunc(r.ActorID, unicode.IsControl) < 0
}
func (p Plan) request() Request {
	r := Request{SchemaVersion: p.wireVersion("local-skill-install-stage-create"), RequestID: p.RequestID, GrantID: p.GrantID, ExpectedRevision: p.GrantRevision, InstanceID: p.InstanceID, DirectoryName: p.DirectoryName, ActorID: p.ActorID}
	if p.TargetRef != nil {
		r.TargetID = p.TargetRef.TargetID
	}
	return r
}
func hash(raw []byte) string             { digest := sha256.Sum256(raw); return hex.EncodeToString(digest[:]) }
func (s *Store) stage(id string) string  { return filepath.Join(s.dir, "stages", id) }
func (s *Store) record(id string) string { return filepath.Join(s.dir, "plans", id+".json") }
func (s *Store) inspect(ctx context.Context, r Request) (Plan, error) {
	var p Plan
	if !validRequest(r) {
		return p, ErrInvalid
	}
	if err := ctx.Err(); err != nil {
		return p, err
	}
	target, reference, destination, display, err := s.inspectRequestTarget(ctx, r)
	if err != nil {
		return p, err
	}
	current, revision, err := s.authority.GetGrantWithSeq(r.GrantID)
	if err != nil || current == nil || revision != r.ExpectedRevision || !grant.Verify(s.key.Public(), *current) || current.Status != "approved" || current.Platform != target.Platform || current.Subject.Type != "agent_instance" || current.Subject.ID != subjectForInstance(r.InstanceID) || grant.ValidateLifetime(*current, s.now()) != nil {
		return p, ErrChanged
	}
	if reference != nil && !planGrantProfile(Plan{SchemaVersion: planV2}, current) {
		return p, ErrChanged
	}
	adm, err := s.authority.GetAdmission(current.AdmissionID)
	if err != nil {
		return p, ErrChanged
	}
	if err := s.imports.ValidatePermissionAdmission(ctx, *adm); err != nil {
		return p, sourceError(ctx, err)
	}
	source, err := importsource.Parse(*adm)
	if err != nil {
		return p, ErrChanged
	}
	permission, err := grant.PermissionDigest(*current)
	if err != nil {
		return p, ErrChanged
	}
	// Full payload validation can take time; sample authority and destination
	// again after it, before signing a preview of the current approved state.
	latest, latestRevision, err := s.authority.GetGrantWithSeq(r.GrantID)
	if err != nil || latest == nil || latestRevision != revision || latest.Signature != current.Signature || !grant.Verify(s.key.Public(), *latest) || grant.ValidateLifetime(*latest, s.now()) != nil {
		return p, ErrChanged
	}
	_, nextRef, nextDestination, nextDisplay, err := s.inspectRequestTarget(ctx, r)
	if err != nil {
		return p, err
	}
	if nextDestination != destination || nextDisplay != display || !sameTargetRef(reference, nextRef) {
		return p, ErrChanged
	}
	p = Plan{SchemaVersion: "local-skill-install-plan/v1", RequestID: r.RequestID, Source: source, GrantID: r.GrantID, GrantRevision: revision, GrantSignature: current.Signature, GrantPermissionDigest: permission, Platform: target.Platform, InstanceID: r.InstanceID, DirectoryName: r.DirectoryName, TargetLocatorDigest: hash([]byte(destination)), TargetDisplay: display, ActorID: r.ActorID, TargetRef: reference}
	if reference != nil {
		p.SchemaVersion = planV2
	}
	if !displayValid(p.TargetDisplay) {
		return Plan{}, ErrInvalid
	}
	p.PlanID, err = p.identity()
	if err != nil {
		return Plan{}, ErrInvalid
	}
	return p, nil
}
func sourceError(ctx context.Context, err error) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if errors.Is(err, skillimport.ErrLimit) {
		return ErrLimit
	}
	return ErrChanged
}
func (s *Store) Stage(ctx context.Context, r Request) (*Plan, bool, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if !validRequest(r) {
		return nil, false, ErrInvalid
	}
	select {
	case stageSlot <- struct{}{}:
		defer func() { <-stageSlot }()
	case <-ctx.Done():
		return nil, false, ctx.Err()
	}
	p, err := s.inspect(ctx, r)
	if err != nil {
		return nil, false, err
	}
	if err := s.checkRequest(p); err != nil {
		return nil, false, err
	}
	if _, err := os.Lstat(s.record(p.PlanID)); err == nil {
		current, err := s.Load(ctx, p.PlanID)
		return current, err == nil, err
	} else if !os.IsNotExist(err) {
		return nil, false, ErrUnavailable
	}
	if err := checkDirectories(filepath.Join(s.dir, "stages")); err != nil {
		return nil, false, err
	}
	directory, err := statefs.Open(filepath.Join(s.dir, "stages"))
	if err != nil {
		return nil, false, ErrUnavailable
	}
	names, err := directory.Readdirnames(maxStages)
	directory.Close()
	if err != nil && err != io.EOF {
		return nil, false, ErrUnavailable
	}
	if len(names) >= maxStages {
		return nil, false, ErrLimit
	}
	stage := s.stage(p.PlanID)
	if err := statefs.Mkdir(stage, 0700); err != nil {
		if os.IsExist(err) {
			return nil, false, ErrConflict
		}
		return nil, false, ErrUnavailable
	}
	published := false
	defer func() {
		if !published {
			_ = statefs.RemoveAll(stage)
		}
	}()
	payload := filepath.Join(stage, "payload")
	if err := statefs.Mkdir(payload, 0700); err != nil {
		return nil, false, ErrUnavailable
	}
	record, err := s.imports.CopyForInstallation(ctx, p.Source.ImportID, payload)
	if err != nil {
		return nil, false, sourceError(ctx, err)
	}
	if err := s.boundary("copied"); err != nil {
		return nil, false, ErrUnavailable
	}
	if err := s.imports.VerifyInstallationCopy(ctx, p.Source.ImportID, payload); err != nil {
		return nil, false, sourceError(ctx, err)
	}
	latest, err := s.inspect(ctx, r)
	if err != nil {
		return nil, false, err
	}
	if latest.PlanID != p.PlanID || latest.TargetDisplay != p.TargetDisplay {
		return nil, false, ErrChanged
	}
	p.FileCount = len(record.Files)
	for _, file := range record.Files {
		p.TotalBytes += file.Bytes
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
	if err := s.publish(p); err != nil {
		return nil, false, err
	}
	published = true
	return &p, false, nil
}
