// Package skillinstall prepares content-bound installation transactions.
// Staging never changes platform files or activates runtime permission.
package skillinstall

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"regexp"
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
}
type Target struct{ InstanceID, Platform, Root, Display string }
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
}
type Store struct {
	dir       string
	key       *signing.Key
	imports   *skillimport.Store
	authority *state.Store
	resolve   func(context.Context, string) (Target, error)
	now       func() time.Time
	// Private test boundary, never set from runtime configuration.
	boundary func(string) error
}

func Open(authority *state.Store, key *signing.Key, imports *skillimport.Store, resolve func(context.Context, string) (Target, error)) (*Store, error) {
	if authority == nil || key == nil || imports == nil || resolve == nil {
		return nil, ErrInvalid
	}
	dir := filepath.Join(authority.Dir, "skill-installations")
	for _, path := range []string{dir, filepath.Join(dir, "plans"), filepath.Join(dir, "stages"), filepath.Join(dir, "operations"), filepath.Join(dir, "runtime-bindings"), filepath.Join(dir, "removals"), filepath.Join(dir, "update-plans"), filepath.Join(dir, "update-stages"), filepath.Join(dir, "update-operations"), filepath.Join(dir, "update-installations")} {
		if err := privateDirectory(path); err != nil {
			return nil, err
		}
	}
	return &Store{dir: dir, key: key, imports: imports, authority: authority, resolve: resolve, now: time.Now, boundary: func(string) error { return nil }}, nil
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
	return r.SchemaVersion == "local-skill-install-stage-create/v1" && requestID.MatchString(r.RequestID) && r.GrantID != "" && len(r.GrantID) <= 256 && r.ExpectedRevision >= 0 && instanceID.MatchString(r.InstanceID) && nameValid(r.DirectoryName) &&
		r.ActorID != "" && strings.TrimSpace(r.ActorID) == r.ActorID && utf8.ValidString(r.ActorID) && utf8.RuneCountInString(r.ActorID) <= 128 && strings.IndexFunc(r.ActorID, unicode.IsControl) < 0
}
func (p Plan) request() Request {
	return Request{"local-skill-install-stage-create/v1", p.RequestID, p.GrantID, p.GrantRevision, p.InstanceID, p.DirectoryName, p.ActorID}
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
	target, err := s.resolve(ctx, r.InstanceID)
	if err != nil || target.InstanceID != r.InstanceID || target.Platform != "hermes" || target.Display == "" || len(target.Display) > 4096 {
		return p, ErrChanged
	}
	destination, err := targetPath(target, r.DirectoryName)
	if err != nil {
		return p, err
	}
	current, revision, err := s.authority.GetGrantWithSeq(r.GrantID)
	if err != nil || current == nil || revision != r.ExpectedRevision || !grant.Verify(s.key.Public(), *current) || current.Status != "approved" || current.Platform != "hermes" || current.Subject.Type != "agent_instance" || current.Subject.ID != "hri-"+strings.TrimPrefix(r.InstanceID, "hi-") || grant.ValidateLifetime(*current, s.now()) != nil {
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
	if _, err := targetPath(target, r.DirectoryName); err != nil {
		return p, err
	}
	p = Plan{SchemaVersion: "local-skill-install-plan/v1", RequestID: r.RequestID, Source: source, GrantID: r.GrantID, GrantRevision: revision, GrantSignature: current.Signature, GrantPermissionDigest: permission, Platform: target.Platform, InstanceID: r.InstanceID, DirectoryName: r.DirectoryName, TargetLocatorDigest: hash([]byte(destination)), TargetDisplay: strings.TrimSuffix(target.Display, "/") + "/skills/" + r.DirectoryName, ActorID: r.ActorID}
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
	directory, err := os.Open(filepath.Join(s.dir, "stages"))
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
