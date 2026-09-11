package skillinstall

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/fileopen"
	"siq-agent-security/apps/agentshield/internal/signing"
)

var digestPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)
var signaturePattern = regexp.MustCompile(`^[a-f0-9]{128}$`)

func document(value any, signature bool) (map[string]any, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	decoded, err := canon.Decode(raw)
	if err != nil {
		return nil, err
	}
	doc, ok := decoded.(map[string]any)
	if !ok {
		return nil, ErrInvalid
	}
	if !signature {
		delete(doc, "signature")
	}
	return doc, nil
}
func (p Plan) identity() (string, error) {
	doc, err := document(map[string]any{"request": p.request(), "source": p.Source, "target_locator_digest": p.TargetLocatorDigest, "grant_signature": p.GrantSignature, "grant_permission_digest": p.GrantPermissionDigest}, true)
	if err != nil {
		return "", err
	}
	raw, err := canon.Marshal(doc)
	if err != nil {
		return "", err
	}
	return "sip-" + hash(raw), nil
}
func displayValid(display string) bool {
	return display != "" && len(display) <= 4096 && utf8.ValidString(display) && strings.IndexFunc(display, unicode.IsControl) < 0
}
func (s *Store) readPlan(id string) (*Plan, error) {
	if !planID.MatchString(id) {
		return nil, ErrInvalid
	}
	if err := checkDirectories(filepath.Dir(s.record(id))); err != nil {
		return nil, err
	}
	before, err := os.Lstat(s.record(id))
	if os.IsNotExist(err) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, ErrUnavailable
	}
	if !before.Mode().IsRegular() || before.Size() > 1<<20 {
		return nil, ErrChanged
	}
	f, err := fileopen.Regular(s.record(id))
	if err != nil {
		return nil, ErrChanged
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(before, opened) {
		return nil, ErrChanged
	}
	raw, err := io.ReadAll(io.LimitReader(f, (1<<20)+1))
	if err != nil || len(raw) > 1<<20 {
		return nil, ErrChanged
	}
	after, err := os.Lstat(s.record(id))
	if err != nil || !os.SameFile(before, after) || before.Mode() != after.Mode() || before.Size() != after.Size() || int64(len(raw)) != before.Size() || !before.ModTime().Equal(after.ModTime()) {
		return nil, ErrChanged
	}
	var p Plan
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&p); err != nil {
		return nil, ErrChanged
	}
	doc, err := document(p, true)
	if err != nil {
		return nil, ErrChanged
	}
	canonical, err := canon.Marshal(doc)
	// Records are written as canonical JSON. Exact typed round-trip also rejects
	// duplicate/case-aliased fields, nulls and trailing documents.
	if err != nil || !bytes.Equal(raw, canonical) {
		return nil, ErrChanged
	}
	if p.SchemaVersion != "local-skill-install-plan/v1" || p.PlanID != id || !validRequest(p.request()) || p.Platform != "hermes" || !displayValid(p.TargetDisplay) || !digestPattern.MatchString(p.TargetLocatorDigest) || !digestPattern.MatchString(p.GrantPermissionDigest) || !signaturePattern.MatchString(p.GrantSignature) || !signaturePattern.MatchString(p.Signature) || p.FileCount < 1 || p.FileCount > 2000 || p.TotalBytes < 0 || p.TotalBytes > 64<<20 || p.Installed || p.RuntimeVerified {
		return nil, ErrChanged
	}
	if _, err := p.Source.Canonical(); err != nil {
		return nil, ErrChanged
	}
	identity, err := p.identity()
	if err != nil || identity != id {
		return nil, ErrChanged
	}
	delete(doc, "signature")
	if !signing.VerifyCanonical(s.key.Public(), doc, p.Signature) {
		return nil, ErrChanged
	}
	created, err := time.Parse(time.RFC3339Nano, p.CreatedAt)
	if err != nil {
		return nil, ErrChanged
	}
	expires, err := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	if err != nil || expires.Sub(created) != planTTL {
		return nil, ErrChanged
	}
	return &p, nil
}
func (s *Store) validTime(p *Plan) error {
	created, _ := time.Parse(time.RFC3339Nano, p.CreatedAt)
	expires, _ := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	now := s.now()
	if now.Before(created) || !now.Before(expires) {
		return ErrExpired
	}
	return nil
}
func (s *Store) Load(ctx context.Context, id string) (*Plan, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	p, err := s.readPlan(id)
	if err != nil {
		return nil, err
	}
	if err := s.validTime(p); err != nil {
		return nil, err
	}
	current, err := s.inspect(ctx, p.request())
	if err != nil {
		return nil, err
	}
	if current.PlanID != p.PlanID || current.TargetDisplay != p.TargetDisplay {
		return nil, ErrChanged
	}
	if err := s.imports.VerifyInstallationCopy(ctx, p.Source.ImportID, filepath.Join(s.stage(id), "payload")); err != nil {
		return nil, sourceError(ctx, err)
	}
	record, _, err := s.imports.Load(ctx, p.Source.ImportID)
	if err != nil {
		return nil, sourceError(ctx, err)
	}
	var total int64
	for _, file := range record.Files {
		total += file.Bytes
	}
	if p.FileCount != len(record.Files) || p.TotalBytes != total {
		return nil, ErrChanged
	}
	current, err = s.inspect(ctx, p.request())
	if err != nil {
		return nil, err
	}
	if current.PlanID != p.PlanID || current.TargetDisplay != p.TargetDisplay {
		return nil, ErrChanged
	}
	if err := s.validTime(p); err != nil {
		return nil, err
	}
	return p, nil
}
func (s *Store) publish(p Plan) error {
	parent := filepath.Dir(s.record(p.PlanID))
	if err := privateDirectory(parent); err != nil {
		return err
	}
	doc, err := document(p, true)
	if err != nil {
		return ErrUnavailable
	}
	raw, err := canon.Marshal(doc)
	if err != nil {
		return ErrUnavailable
	}
	f, err := os.CreateTemp(parent, ".plan-*")
	if err != nil {
		return ErrUnavailable
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(raw); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil || closeErr != nil {
		return ErrUnavailable
	}
	if err := os.Link(f.Name(), s.record(p.PlanID)); err != nil {
		if os.IsExist(err) {
			return ErrConflict
		}
		return ErrUnavailable
	}
	return nil
}

// A request ID cannot silently acquire another target or authority after a
// response is lost. Inspect bounded signed metadata, including expired plans.
func (s *Store) checkRequest(candidate Plan) error {
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
	if len(names) > maxStages*2 {
		return ErrLimit
	}
	for _, name := range names {
		if strings.HasPrefix(name, ".plan-") {
			continue
		}
		id := strings.TrimSuffix(name, ".json")
		if name != id+".json" || !planID.MatchString(id) {
			return ErrChanged
		}
		existing, err := s.readPlan(id)
		if err != nil {
			return err
		}
		if existing.RequestID == candidate.RequestID && existing.PlanID != candidate.PlanID {
			return ErrConflict
		}
	}
	return nil
}
