package skillcontext

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/importsource"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

// Deps injects live readers for every fact a SEC depends on. Verification
// re-reads each one on every call; nothing is cached across decisions.
type Deps struct {
	Key *signing.Key
	Now func() time.Time
	// ReadGrant returns the current stored grant document, whatever its state.
	ReadGrant func(grantID string) (*grant.Grant, error)
	// ReadInstall returns the current signed install record.
	ReadInstall func(installID string) (*skillinstall.Record, error)
	// ReadInstance returns the signed runtime identity record when it exists
	// and is not revoked.
	ReadInstance func(instanceID string) (runtimeidentity.Record, error)
	// SessionBound confirms the session completed managed enrollment pinned to
	// the given grant and returns the signed binding expiry. SEC lifetime is
	// clamped to that boundary and the binding is re-read on every decision.
	SessionBound func(platform, agentID, sessionID, grantID string) (time.Time, error)
}

// Store persists SECs under <state>/skill-contexts and their tombstones under
// <state>/skill-context-revocations. Files are published exclusively and are
// never rewritten in place.
type Store struct {
	dir  string
	deps Deps
}

// IssueRequest identifies the controlled subject by stored identities only;
// skill identity and authority digests are derived, never caller supplied.
type IssueRequest struct {
	InstanceID string
	SessionID  string
	TaskID     string
	InstallID  string
	TTL        time.Duration
}

// Verification is the per-decision outcome for one request subject. A nil
// *Verification means no SEC covers the subject at all (the request follows
// the pre-SEC claim path). Invalid reports a SEC that matched the subject but
// failed verification: callers must deny, never fall back. Grant is the
// SEC-bound live grant, re-validated during verification.
type Verification struct {
	Context    *Context
	Grant      *grant.Grant
	Invalid    bool
	ReasonCode string
}

var mu sync.RWMutex

// Open prepares the SEC directories. The daemon state-writer lock supplies
// cross-process exclusion; mu serializes in-process access.
func Open(dir string, deps Deps) (*Store, error) {
	if !filepath.IsAbs(dir) || deps.Key == nil || deps.ReadGrant == nil || deps.ReadInstall == nil || deps.ReadInstance == nil || deps.SessionBound == nil {
		return nil, invalid("")
	}
	if deps.Now == nil {
		deps.Now = func() time.Time { return time.Now().UTC() }
	}
	dir = filepath.Clean(dir)
	for _, name := range []string{"skill-contexts", "skill-context-revocations"} {
		d := filepath.Join(dir, name)
		if err := statefs.MkdirAll(d, 0o700); err != nil {
			return nil, invalid("")
		}
		if err := statefs.Chmod(d, 0o700); err != nil {
			return nil, invalid("")
		}
	}
	return &Store{dir: dir, deps: deps}, nil
}

func (s *Store) contextDir() string           { return filepath.Join(s.dir, "skill-contexts") }
func (s *Store) revokedDir() string           { return filepath.Join(s.dir, "skill-context-revocations") }
func (s *Store) contextPath(id string) string { return filepath.Join(s.contextDir(), id+".json") }
func (s *Store) revokedPath(id string) string { return filepath.Join(s.revokedDir(), id+".json") }

// GrantDigest is the canonical-bytes sha256 of a grant document. Any field
// change (including status flips) produces a different digest.
func GrantDigest(g *grant.Grant) (string, error) {
	raw, err := json.Marshal(g)
	if err != nil {
		return "", invalid("")
	}
	var m map[string]any
	if err := json.Unmarshal(raw, &m); err != nil {
		return "", invalid("")
	}
	b, err := canon.Marshal(m)
	if err != nil {
		return "", invalid("")
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:]), nil
}

// grantLive enforces the same live criteria the engine applies to an
// explicitly selected grant: deployed/effective, or the install pipeline's
// terminal state (approved with an import-reserved admission). The reserved
// form is only meaningful together with a matching install record, which
// issuance and verification both require.
func grantLive(g *grant.Grant, now time.Time) bool {
	if g.Status != "deployed" && g.Status != "effective" &&
		!(g.Status == "approved" && importsource.Reserved(g.AdmissionID)) {
		return false
	}
	return grant.ValidateLifetime(*g, now) == nil
}

// liveGrant enforces every current-state rule a SEC depends on.
func (s *Store) liveGrant(grantID, digest string, now time.Time) (*grant.Grant, error) {
	g, err := s.deps.ReadGrant(grantID)
	if err != nil || g == nil {
		return nil, invalid("skill_context_grant_changed")
	}
	if !grantLive(g, now) {
		return nil, invalid("skill_context_grant_changed")
	}
	d, err := GrantDigest(g)
	if err != nil || d != digest {
		return nil, invalid("skill_context_grant_changed")
	}
	return g, nil
}

// liveInstall enforces the install record presence and identity pinned at
// issuance. Removal, recovery states or plan drift all invalidate.
func (s *Store) liveInstall(ref InstallRef, g *grant.Grant) error {
	rec, err := s.deps.ReadInstall(ref.InstallID)
	if err != nil || rec == nil {
		return invalid("skill_context_install_changed")
	}
	if rec.SchemaVersion != "local-skill-install-record/v1" || rec.RecordedStatus != "installed_unverified" ||
		rec.ClaimSignature != ref.ClaimSignature || rec.Plan.GrantID != g.GrantID {
		return invalid("skill_context_install_changed")
	}
	return nil
}

// Issue signs and publishes a SEC after every prerequisite re-reads live
// state. It refuses caller-supplied authority digests by construction: the
// request carries identities only.
func (s *Store) Issue(req IssueRequest) (*Context, error) {
	mu.Lock()
	defer mu.Unlock()
	if !instancePattern.MatchString(req.InstanceID) || !textValid(req.SessionID, 256) || req.InstallID == "" {
		return nil, invalid("")
	}
	if req.TTL <= 0 || req.TTL > MaxTTL {
		return nil, invalid("")
	}
	now := s.deps.Now()
	inst, err := s.deps.ReadInstance(req.InstanceID)
	if err != nil {
		return nil, invalid("skill_context_instance_invalid")
	}
	agentID, err := runtimeidentity.AgentID(req.InstanceID)
	if err != nil || inst.AgentID != agentID {
		return nil, invalid("skill_context_instance_invalid")
	}
	install, err := s.deps.ReadInstall(req.InstallID)
	if err != nil || install == nil {
		return nil, invalid("skill_context_install_changed")
	}
	if install.SchemaVersion != "local-skill-install-record/v1" || install.RecordedStatus != "installed_unverified" ||
		install.Plan.Platform != inst.Platform || install.Plan.InstanceID != req.InstanceID {
		return nil, invalid("skill_context_install_changed")
	}
	g, err := s.deps.ReadGrant(install.Plan.GrantID)
	if err != nil || g == nil || g.Skill == nil || g.Platform != inst.Platform || g.Subject.ID != agentID {
		return nil, invalid("skill_context_grant_changed")
	}
	if !grantLive(g, now) {
		return nil, invalid("skill_context_grant_changed")
	}
	digest, err := GrantDigest(g)
	if err != nil {
		return nil, invalid("")
	}
	// The instance's pinned grant and the enrolled session binding must both
	// reference the grant the skill was installed under.
	if inst.GrantRef.GrantID != g.GrantID {
		return nil, invalid("skill_context_grant_changed")
	}
	boundUntil, err := s.deps.SessionBound(inst.Platform, agentID, req.SessionID, g.GrantID)
	if err != nil || !now.Before(boundUntil) {
		return nil, invalid("skill_context_session_unbound")
	}
	subject := Subject{Platform: inst.Platform, InstanceID: req.InstanceID, AgentID: agentID, SessionID: req.SessionID, TaskID: req.TaskID}
	level := EvidenceSession
	if req.TaskID != "" {
		level = EvidenceTask
	}
	if existing, err := s.activeConflict(subject, now); err != nil {
		return nil, invalid("")
	} else if existing != nil {
		return nil, invalid("skill_context_conflict")
	}
	skill := SkillRef{SkillID: g.Skill.SkillID, ContentHash: g.Skill.ContentHash}
	if g.Skill.Version != nil {
		skill.Version = *g.Skill.Version
	}
	expiresAt := now.UTC().Add(req.TTL)
	if boundUntil.Before(expiresAt) {
		expiresAt = boundUntil
	}
	contextID, err := newID()
	if err != nil {
		return nil, invalid("")
	}
	c := Context{
		SchemaVersion: Schema,
		ContextID:     contextID,
		IssuerID:      Issuer,
		Subject:       subject,
		Skill:         skill,
		Install:       InstallRef{InstallID: req.InstallID, ClaimSignature: install.ClaimSignature},
		Authority:     AuthorityRef{GrantID: g.GrantID, GrantDigest: digest},
		EvidenceLevel: level,
		IssuedAt:      now.UTC().Format(time.RFC3339Nano),
		ExpiresAt:     expiresAt.UTC().Format(time.RFC3339Nano),
		SigningSchema: signing.SchemaLocalCanonicalV1,
	}
	if err := c.Validate(); err != nil {
		return nil, err
	}
	ids, err := s.contextIDs()
	if err != nil || len(ids) >= maxContexts {
		return nil, invalid("")
	}
	c.Signature, err = s.deps.Key.SignCanonical(c.Unsigned())
	if err != nil {
		return nil, invalid("")
	}
	raw, err := json.MarshalIndent(c, "", "  ")
	if err != nil || len(raw) > maxContextBytes {
		return nil, invalid("")
	}
	if err = publish(s.contextPath(c.ContextID), append(raw, '\n')); err != nil {
		if errors.Is(err, os.ErrExist) {
			return nil, invalid("skill_context_conflict")
		}
		return nil, invalid("")
	}
	return &c, nil
}

// Revoke publishes a signed tombstone. The original SEC file is retained.
func (s *Store) Revoke(contextID string) (*Revocation, error) {
	return s.RevokeExpected(contextID, "")
}

// RevokeExpected publishes a tombstone only when the caller's readback still
// identifies the exact immutable SEC. An empty expected signature is retained
// for the offline compatibility wrapper Revoke; online management must always
// supply one.
func (s *Store) RevokeExpected(contextID, expectedSignature string) (*Revocation, error) {
	mu.Lock()
	defer mu.Unlock()
	if !contextIDPattern.MatchString(contextID) {
		return nil, invalid("")
	}
	c, err := s.read(contextID)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, invalid("skill_context_not_found")
		}
		return nil, invalid("")
	}
	if expectedSignature != "" && (!hex128Pattern.MatchString(expectedSignature) || c.Signature != expectedSignature) {
		return nil, invalid("skill_context_changed")
	}
	r := Revocation{
		SchemaVersion: RevocationSchema,
		ContextID:     contextID,
		IssuerID:      Issuer,
		RevokedAt:     s.deps.Now().UTC().Format(time.RFC3339Nano),
		SigningSchema: signing.SchemaLocalCanonicalV1,
	}
	if err := r.Validate(); err != nil {
		return nil, err
	}
	sig, err := s.deps.Key.SignCanonical(r.Unsigned())
	if err != nil {
		return nil, invalid("")
	}
	r.Signature = sig
	raw, err := json.MarshalIndent(r, "", "  ")
	if err != nil || len(raw) > maxContextBytes {
		return nil, invalid("")
	}
	if err = publish(s.revokedPath(contextID), append(raw, '\n')); err != nil {
		if errors.Is(err, os.ErrExist) {
			return nil, invalid("skill_context_conflict")
		}
		return nil, invalid("")
	}
	return &r, nil
}

// Verify resolves the SEC covering one request subject. It re-verifies the
// signature, expiry, revocation and every live dependency on each call.
func (s *Store) Verify(platform, agentID, sessionID, taskID string) (*Verification, error) {
	mu.RLock()
	defer mu.RUnlock()
	now := s.deps.Now()
	ids, err := s.contextIDs()
	if err != nil {
		return nil, invalid("")
	}
	matched := []*Context{}
	for _, id := range ids {
		c, err := s.read(id)
		if err != nil {
			return nil, invalid("")
		}
		if c.Subject.Platform != platform || c.Subject.AgentID != agentID || c.Subject.SessionID != sessionID {
			continue
		}
		if c.Subject.TaskID != "" && c.Subject.TaskID != taskID {
			continue
		}
		matched = append(matched, c)
	}
	if len(matched) == 0 {
		return nil, nil
	}
	sort.Slice(matched, func(i, j int) bool { return matched[i].ContextID < matched[j].ContextID })
	code := ""
	for _, c := range matched {
		if g, err := s.verifyOne(c, now); err == nil {
			return &Verification{Context: c, Grant: g}, nil
		} else {
			var v *Violation
			if errors.As(err, &v) && v.Code != "skill_context_invalid" {
				code = v.Code
			}
		}
	}
	if code == "" {
		code = "skill_context_invalid"
	}
	return &Verification{Invalid: true, ReasonCode: code}, nil
}

// verifyOne runs every check for one SEC. Any failure invalidates.
func (s *Store) verifyOne(c *Context, now time.Time) (*grant.Grant, error) {
	expires, err := time.Parse(time.RFC3339Nano, c.ExpiresAt)
	if err != nil || !now.Before(expires) {
		return nil, invalid("skill_context_expired")
	}
	if revoked, err := s.revoked(c.ContextID); err != nil {
		return nil, invalid("")
	} else if revoked {
		return nil, invalid("skill_context_revoked")
	}
	inst, err := s.deps.ReadInstance(c.Subject.InstanceID)
	if err != nil || inst.Platform != c.Subject.Platform || inst.AgentID != c.Subject.AgentID ||
		inst.GrantRef.GrantID != c.Authority.GrantID {
		return nil, invalid("skill_context_instance_invalid")
	}
	g, err := s.liveGrant(c.Authority.GrantID, c.Authority.GrantDigest, now)
	if err != nil {
		return nil, err
	}
	if err := s.liveInstall(c.Install, g); err != nil {
		return nil, err
	}
	boundUntil, err := s.deps.SessionBound(c.Subject.Platform, c.Subject.AgentID, c.Subject.SessionID, c.Authority.GrantID)
	if err != nil || !now.Before(boundUntil) || expires.After(boundUntil) {
		return nil, invalid("skill_context_session_unbound")
	}
	if g.Skill == nil || g.Skill.SkillID != c.Skill.SkillID || g.Skill.ContentHash != c.Skill.ContentHash ||
		(g.Skill.Version != nil && c.Skill.Version != *g.Skill.Version) {
		return nil, invalid("skill_context_invalid")
	}
	return g, nil
}

// activeConflict returns an overlapping active SEC. A session-scoped context
// conflicts with every task context in that session; task-scoped contexts may
// coexist only for distinct tasks. This prevents random context-ID ordering
// from selecting another Skill's session authority.
func (s *Store) activeConflict(subject Subject, now time.Time) (*Context, error) {
	ids, err := s.contextIDs()
	if err != nil {
		return nil, err
	}
	for _, id := range ids {
		c, err := s.read(id)
		if err != nil {
			return nil, err
		}
		if c.Subject.Platform != subject.Platform || c.Subject.InstanceID != subject.InstanceID ||
			c.Subject.AgentID != subject.AgentID || c.Subject.SessionID != subject.SessionID {
			continue
		}
		if c.Subject.TaskID != "" && subject.TaskID != "" && c.Subject.TaskID != subject.TaskID {
			continue
		}
		expires, err := time.Parse(time.RFC3339Nano, c.ExpiresAt)
		if err != nil {
			return nil, invalid("")
		}
		if !now.Before(expires) {
			continue
		}
		revoked, err := s.revoked(id)
		if err != nil {
			return nil, invalid("")
		}
		if !revoked {
			return c, nil
		}
	}
	return nil, nil
}

// read loads one SEC and enforces shape plus signature.
func (s *Store) read(id string) (*Context, error) {
	if !contextIDPattern.MatchString(id) {
		return nil, invalid("")
	}
	var c Context
	if err := readRecord(s.contextPath(id), &c); err != nil {
		return nil, err
	}
	if c.ContextID != id || c.Validate() != nil || signing.VerifyWithSchema(c.SigningSchema, s.deps.Key.Public(), c.Unsigned(), c.Signature) != nil {
		return nil, invalid("")
	}
	return &c, nil
}

// revoked reports whether a valid signed tombstone exists.
func (s *Store) revoked(id string) (bool, error) {
	var r Revocation
	err := readRecord(s.revokedPath(id), &r)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, invalid("")
	}
	if r.ContextID != id || r.Validate() != nil || signing.VerifyWithSchema(r.SigningSchema, s.deps.Key.Public(), r.Unsigned(), r.Signature) != nil {
		return false, invalid("")
	}
	return true, nil
}

// Get returns one verified SEC for management display.
func (s *Store) Get(id string) (*Context, error) {
	mu.RLock()
	defer mu.RUnlock()
	c, err := s.read(id)
	if errors.Is(err, os.ErrNotExist) {
		return nil, invalid("skill_context_not_found")
	}
	return c, err
}

func (s *Store) contextIDs() ([]string, error) {
	f, err := statefs.Open(s.contextDir())
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return []string{}, nil
		}
		return nil, invalid("")
	}
	defer f.Close()
	entries, err := f.ReadDir(maxContexts + 1)
	if err != nil && err != io.EOF {
		return nil, invalid("")
	}
	if len(entries) > maxContexts {
		return nil, invalid("")
	}
	ids := []string{}
	for _, e := range entries {
		if strings.HasPrefix(e.Name(), ".") {
			continue
		}
		id, ok := strings.CutSuffix(e.Name(), ".json")
		if !ok || !contextIDPattern.MatchString(id) {
			return nil, invalid("")
		}
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids, nil
}

func newID() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return "sec-" + hex.EncodeToString(b[:]), nil
}

// publish writes a complete fsynced file exclusively; it never exposes a
// partially written context.
func publish(path string, b []byte) error {
	f, err := statefs.CreateTemp(filepath.Dir(path), ".skill-context-*")
	if err != nil {
		return err
	}
	defer statefs.Remove(f.Name())
	if _, err = f.Write(b); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	if err := statefs.Link(f.Name(), path); err != nil {
		return err
	}
	return nil
}

func readRecord(path string, out any) error {
	fi, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !fi.Mode().IsRegular() || fi.Size() > maxContextBytes {
		return invalid("")
	}
	f, err := statefs.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	dec := json.NewDecoder(io.LimitReader(f, maxContextBytes+1))
	dec.DisallowUnknownFields()
	if err := dec.Decode(out); err != nil {
		return invalid("")
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		return invalid("")
	}
	return nil
}
