package skillcontext

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

const InvocationRevocationSchema = "skill-execution-context-revocation/v2"
const maxInvocations = 4096
const maxInvocationDepth = 8

// InvocationDeps must be supplied by the trusted host. ReadInstance and
// ReadInstall authenticate their signed records. ValidateInstalled checks the
// current installed bytes. ValidateLoad authenticates the native task/load,
// including its exact parent (nil is an attested root, never unknown lineage).
// Neither callback may accept model-supplied declarations as proof.
type InvocationDeps struct {
	Deps
	ValidateInstalled func(*grant.Grant, InstallRef) error
	ValidateLoad      func(Subject, InstallRef, NativeLoadRef, *ParentRef) (time.Time, error)
	Audit             func(event, contextID string) error
}

// InvocationStore is not an execution authorizer. Its caller must hold the
// daemon's cross-process state-writer lock. mu only serializes this process.
type InvocationStore struct {
	dir  string
	deps InvocationDeps
}

type InvocationRequest struct {
	InstanceID, SessionID, TaskID, InstallID string
	Loader                                   NativeLoadRef
	Parent                                   *ParentRef
	TTL                                      time.Duration
}

// InvocationVerification contains independent snapshots, in leaf-to-root order.
// The eventual engine must intersect all SkillGrants with this exact AgentGrant.
type InvocationVerification struct {
	Contexts    []*InvocationContext
	AgentGrant  *grant.Grant
	SkillGrants []*grant.Grant
}

type InvocationRevocation struct {
	Revocation
	ContextSignature string `json:"context_signature"`
}

func (r *InvocationRevocation) unsigned() map[string]any {
	b, _ := json.Marshal(r)
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	delete(m, "signature")
	return m
}

func OpenInvocations(dir string, deps InvocationDeps) (*InvocationStore, error) {
	if !filepath.IsAbs(dir) || deps.Key == nil || deps.ReadGrant == nil || deps.ReadInstall == nil ||
		deps.ReadInstance == nil || deps.SessionBound == nil || deps.ValidateInstalled == nil ||
		deps.ValidateLoad == nil || deps.Audit == nil {
		return nil, invalid("")
	}
	if deps.Now == nil {
		deps.Now = func() time.Time { return time.Now().UTC() }
	}
	s := &InvocationStore{dir: filepath.Clean(dir), deps: deps}
	for _, d := range []string{s.contextDir(), s.revokedDir()} {
		if err := invocationPrivateDir(d); err != nil {
			return nil, invalid("")
		}
	}
	return s, nil
}

func (s *InvocationStore) contextDir() string { return filepath.Join(s.dir, "skill-contexts-v2") }
func (s *InvocationStore) revokedDir() string {
	return filepath.Join(s.dir, "skill-context-revocations-v2")
}
func (s *InvocationStore) contextPath(id string) string {
	return filepath.Join(s.contextDir(), id+".json")
}
func (s *InvocationStore) revokedPath(id string) string {
	return filepath.Join(s.revokedDir(), id+".json")
}

func invocationID(subject Subject, loadID string) string {
	raw, _ := json.Marshal(subject)
	var sub map[string]any
	_ = json.Unmarshal(raw, &sub)
	b, _ := canon.Marshal(map[string]any{"domain": InvocationSchema, "subject": sub, "load_id": loadID})
	h := sha256.Sum256(b)
	return "sec-" + hex.EncodeToString(h[:16])
}

func (s *InvocationStore) read(id string) (*InvocationContext, error) {
	if !contextIDPattern.MatchString(id) {
		return nil, invalid("")
	}
	var c InvocationContext
	if err := readInvocationJSON(s.contextPath(id), &c); err != nil {
		return nil, err
	}
	if c.ContextID != id || invocationID(c.Subject, c.Loader.LoadID) != id || c.VerifySignature(s.deps.Key.Public()) != nil {
		return nil, invalid("")
	}
	return &c, nil
}

func (s *InvocationStore) readRevocation(c *InvocationContext) (*InvocationRevocation, error) {
	var r InvocationRevocation
	if err := readInvocationJSON(s.revokedPath(c.ContextID), &r); err != nil {
		return nil, err
	}
	base := r.Revocation
	base.SchemaVersion = RevocationSchema
	if r.SchemaVersion != InvocationRevocationSchema || r.SigningSchema != signing.SchemaLocalCanonicalV1 ||
		base.Validate() != nil || r.ContextID != c.ContextID || r.ContextSignature != c.Signature ||
		signing.VerifyWithSchema(r.SigningSchema, s.deps.Key.Public(), r.unsigned(), r.Signature) != nil {
		return nil, invalid("")
	}
	return &r, nil
}

// snapshotGrant verifies a deep copy: later dependency mutations cannot change
// the authority returned to the caller without another verification.
func (s *InvocationStore) snapshotGrant(id string, now time.Time) (*grant.Grant, error) {
	g, err := s.deps.ReadGrant(id)
	if err != nil || g == nil {
		return nil, invalid("skill_context_grant_changed")
	}
	b, err := json.Marshal(g)
	var snapshot grant.Grant
	if err != nil || json.Unmarshal(b, &snapshot) != nil || snapshot.GrantID != id ||
		!grant.Verify(s.deps.Key.Public(), snapshot) || !grantLive(&snapshot, now) {
		return nil, invalid("skill_context_grant_changed")
	}
	return &snapshot, nil
}

func (s *InvocationStore) live(c *InvocationContext, now time.Time) (*grant.Grant, *grant.Grant, time.Time, error) {
	fail := func() (*grant.Grant, *grant.Grant, time.Time, error) {
		return nil, nil, time.Time{}, invalid("skill_context_dependency_changed")
	}
	inst, err := s.deps.ReadInstance(c.Subject.InstanceID)
	if err != nil || inst.InstanceID != c.Subject.InstanceID || inst.AgentID != c.Subject.AgentID ||
		inst.Platform != c.Subject.Platform || inst.GrantRef.GrantID != c.AgentAuthority.GrantID {
		return fail()
	}
	a, err := s.snapshotGrant(c.AgentAuthority.GrantID, now)
	if err != nil || a.Skill != nil || (a.Status != "deployed" && a.Status != "effective") {
		return fail()
	}
	g, err := s.snapshotGrant(c.Authority.GrantID, now)
	if err != nil || g.Skill == nil {
		return fail()
	}
	for _, pair := range []struct {
		g   *grant.Grant
		ref AuthorityRef
	}{{a, c.AgentAuthority}, {g, c.Authority}} {
		d, err := GrantDigest(pair.g)
		if err != nil || d != pair.ref.GrantDigest || pair.g.Platform != c.Subject.Platform ||
			pair.g.Subject.Type != "agent_instance" || pair.g.Subject.ID != c.Subject.AgentID {
			return fail()
		}
	}
	if skillReference(g) != c.Skill {
		return fail()
	}
	r, err := s.deps.ReadInstall(c.Install.InstallID)
	if err != nil || r == nil || !skillinstall.ValidRecordVersion(r) || r.InstallID != c.Install.InstallID ||
		r.RecordedStatus != "installed_unverified" || r.ClaimSignature != c.Install.ClaimSignature ||
		r.Plan.GrantID != g.GrantID || r.Plan.InstanceID != c.Subject.InstanceID || r.Plan.Platform != c.Subject.Platform {
		return fail()
	}
	if s.deps.ValidateInstalled(g, c.Install) != nil {
		return fail()
	}
	until, err := s.deps.SessionBound(c.Subject.Platform, c.Subject.AgentID, c.Subject.SessionID, a.GrantID)
	if err != nil || !now.Before(until) {
		return fail()
	}
	loadUntil, err := s.deps.ValidateLoad(c.Subject, c.Install, c.Loader, c.Parent)
	if err != nil || !now.Before(loadUntil) {
		return fail()
	}
	if loadUntil.Before(until) {
		until = loadUntil
	}
	return a, g, until, nil
}

func skillReference(g *grant.Grant) SkillRef {
	r := SkillRef{SkillID: g.Skill.SkillID, ContentHash: g.Skill.ContentHash}
	if g.Skill.Version != nil {
		r.Version = *g.Skill.Version
	}
	return r
}

// Verify fails closed, including missing records. It is not a v1 fallback path.
func (s *InvocationStore) Verify(id string, subject Subject) (*InvocationVerification, error) {
	mu.RLock()
	defer mu.RUnlock()
	return s.verify(id, subject, s.deps.Now())
}

func (s *InvocationStore) verify(id string, subject Subject, now time.Time) (*InvocationVerification, error) {
	result := &InvocationVerification{}
	seen := map[string]bool{}
	var expected *ParentRef
	var authority AuthorityRef
	var childExpiry time.Time
	for {
		if seen[id] || len(result.Contexts) >= maxInvocationDepth {
			return nil, invalid("skill_context_parent_invalid")
		}
		seen[id] = true
		c, err := s.read(id)
		if err != nil || c.Subject != subject || (expected != nil && c.Signature != expected.Signature) {
			return nil, invalid("")
		}
		if _, err := s.readRevocation(c); !errors.Is(err, os.ErrNotExist) {
			return nil, invalid("skill_context_revoked")
		}
		issued, _ := time.Parse(time.RFC3339Nano, c.IssuedAt)
		expires, _ := time.Parse(time.RFC3339Nano, c.ExpiresAt)
		if now.Before(issued) || !now.Before(expires) || (!childExpiry.IsZero() && childExpiry.After(expires)) {
			return nil, invalid("skill_context_expired")
		}
		a, g, until, err := s.live(c, now)
		if err != nil || expires.After(until) {
			return nil, invalid("skill_context_dependency_changed")
		}
		if len(result.Contexts) == 0 {
			authority = c.AgentAuthority
			result.AgentGrant = a
		} else if c.AgentAuthority != authority {
			return nil, invalid("skill_context_parent_invalid")
		}
		result.Contexts = append(result.Contexts, c)
		result.SkillGrants = append(result.SkillGrants, g)
		if c.Parent == nil {
			return result, nil
		}
		expected = c.Parent
		id, childExpiry = expected.ContextID, expires
	}
}

func (s *InvocationStore) Issue(req InvocationRequest) (*InvocationContext, error) {
	mu.Lock()
	defer mu.Unlock()
	if !instancePattern.MatchString(req.InstanceID) || !textValid(req.SessionID, 256) || !textValid(req.TaskID, 256) ||
		!textValid(req.InstallID, 128) || req.TTL <= 0 || req.TTL > InvocationMaxTTL {
		return nil, invalid("")
	}
	now := s.deps.Now().UTC()
	inst, err := s.deps.ReadInstance(req.InstanceID)
	if err != nil {
		return nil, invalid("")
	}
	r, err := s.deps.ReadInstall(req.InstallID)
	if err != nil || r == nil {
		return nil, invalid("")
	}
	a, err := s.snapshotGrant(inst.GrantRef.GrantID, now)
	if err != nil {
		return nil, err
	}
	g, err := s.snapshotGrant(r.Plan.GrantID, now)
	if err != nil || g.Skill == nil {
		return nil, invalid("")
	}
	ad, err := GrantDigest(a)
	if err != nil {
		return nil, err
	}
	gd, err := GrantDigest(g)
	if err != nil {
		return nil, err
	}
	subject := Subject{Platform: inst.Platform, InstanceID: req.InstanceID, AgentID: inst.AgentID, SessionID: req.SessionID, TaskID: req.TaskID}
	c := &InvocationContext{Context: Context{
		SchemaVersion: InvocationSchema, ContextID: invocationID(subject, req.Loader.LoadID), IssuerID: Issuer, Subject: subject,
		Skill: skillReference(g), Install: InstallRef{InstallID: req.InstallID, ClaimSignature: r.ClaimSignature},
		Authority: AuthorityRef{GrantID: g.GrantID, GrantDigest: gd}, EvidenceLevel: EvidenceInvocation,
		IssuedAt: now.Format(time.RFC3339Nano), ExpiresAt: now.Add(req.TTL).Format(time.RFC3339Nano), SigningSchema: signing.SchemaLocalCanonicalV1,
	}, AgentAuthority: AuthorityRef{GrantID: a.GrantID, GrantDigest: ad}, Loader: req.Loader}
	if req.Parent != nil {
		parent := *req.Parent
		c.Parent = &parent
	}
	if c.Validate() != nil {
		return nil, invalid("")
	}
	_, _, until, err := s.live(c, now)
	if err != nil {
		return nil, err
	}
	expires := now.Add(req.TTL)
	if until.Before(expires) {
		expires = until
	}
	if c.Parent != nil {
		p, err := s.verify(c.Parent.ContextID, subject, now)
		if err != nil || len(p.Contexts) >= maxInvocationDepth || p.Contexts[0].Signature != c.Parent.Signature ||
			p.Contexts[0].AgentAuthority != c.AgentAuthority {
			return nil, invalid("skill_context_parent_invalid")
		}
		parentExpiry, _ := time.Parse(time.RFC3339Nano, p.Contexts[0].ExpiresAt)
		if parentExpiry.Before(expires) {
			expires = parentExpiry
		}
	}
	c.ExpiresAt = expires.UTC().Format(time.RFC3339Nano)
	if old, err := s.read(c.ContextID); err == nil {
		// Compare every immutable source field, but never extend original lifetime.
		candidate := *c
		candidate.IssuedAt, candidate.ExpiresAt, candidate.Signature = old.IssuedAt, old.ExpiresAt, old.Signature
		left, _ := json.Marshal(candidate)
		right, _ := json.Marshal(old)
		if string(left) != string(right) {
			return nil, invalid("skill_context_conflict")
		}
		if _, err := s.verify(old.ContextID, subject, now); err != nil {
			return nil, err
		}
		return old, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return nil, invalid("")
	}
	if err := s.capacity(); err != nil {
		return nil, err
	}
	c.Signature, err = s.deps.Key.SignCanonical(c.Unsigned())
	if err != nil || c.VerifySignature(s.deps.Key.Public()) != nil {
		return nil, invalid("")
	}
	if err := s.publish("skill_context_v2_issue_attempt", s.contextPath(c.ContextID), c.ContextID, c); err != nil {
		return nil, err
	}
	return c, nil
}

func (s *InvocationStore) capacity() error {
	if err := invocationAncestors(s.contextDir()); err != nil {
		return invalid("")
	}
	f, err := statefs.Open(s.contextDir())
	if err != nil {
		return invalid("")
	}
	defer f.Close()
	entries, err := f.ReadDir(maxInvocations + 1)
	if (err != nil && err != io.EOF) || len(entries) >= maxInvocations {
		return invalid("skill_context_capacity")
	}
	for _, e := range entries {
		if strings.HasPrefix(e.Name(), ".skill-invocation-") {
			continue
		}
		id, ok := strings.CutSuffix(e.Name(), ".json")
		if !ok || !contextIDPattern.MatchString(id) || !e.Type().IsRegular() {
			return invalid("")
		}
	}
	return nil
}

func (s *InvocationStore) publish(event, path, id string, doc any) error {
	b, err := json.MarshalIndent(doc, "", "  ")
	if err != nil || len(b)+1 > invocationRecordBytes {
		return invalid("")
	}
	if s.deps.Audit(event, id) != nil {
		return invalid("skill_context_audit_unavailable")
	}
	if invocationPublish(path, append(b, '\n')) != nil {
		return invalid("skill_context_publication_failed")
	}
	return nil
}

// Revoke requires the exact original signature, even for duplicate requests.
// It remains available after live dependencies expire or are removed.
func (s *InvocationStore) Revoke(id, expectedSignature string) (*InvocationRevocation, error) {
	mu.Lock()
	defer mu.Unlock()
	c, err := s.read(id)
	if err != nil || !hex128Pattern.MatchString(expectedSignature) || c.Signature != expectedSignature {
		return nil, invalid("skill_context_changed")
	}
	if old, err := s.readRevocation(c); err == nil {
		return old, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return nil, invalid("")
	}
	r := &InvocationRevocation{Revocation: Revocation{SchemaVersion: InvocationRevocationSchema, ContextID: id, IssuerID: Issuer,
		RevokedAt: s.deps.Now().UTC().Format(time.RFC3339Nano), SigningSchema: signing.SchemaLocalCanonicalV1}, ContextSignature: c.Signature}
	r.Signature, err = s.deps.Key.SignCanonical(r.unsigned())
	if err != nil {
		return nil, invalid("")
	}
	if err := s.publish("skill_context_v2_revoke_attempt", s.revokedPath(id), id, r); err != nil {
		return nil, err
	}
	return r, nil
}
