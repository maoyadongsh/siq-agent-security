package skillcontext

import (
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

const maxNativeSessions = 1024
const maxNativeCalls = 16384

// CallDeps is implemented by the trusted native host. Each callback verifies
// facts independently of the document offered here and returns the live lease.
// ValidateCall must prove exact parameters/lineage, or an explicitly empty
// lineage for NoSkill. Model messages and best-effort telemetry are insufficient.
type CallDeps struct {
	ValidateSession func(NativeSession) (time.Time, error)
	ValidateCall    func(NativeCall) (time.Time, error)
}

type NativeCallStore struct {
	contexts *InvocationStore
	deps     CallDeps
}

type NativeSessionRequest struct {
	InstanceID, SessionID, RuntimeArtifactSHA256 string
	TTL                                          time.Duration
}

type NativeCallRequest struct {
	Subject          Subject
	Tool, ToolCallID string
	Params           map[string]any
	Context          *ParentRef
	NoSkill          bool
	TTL              time.Duration
}

type NativeCallVerification struct {
	Call       *NativeCall
	Session    *NativeSession
	AgentGrant *grant.Grant
	Invocation *InvocationVerification // nil only for an explicitly attested NoSkill
}

func OpenNativeCalls(contexts *InvocationStore, deps CallDeps) (*NativeCallStore, error) {
	if contexts == nil || deps.ValidateSession == nil || deps.ValidateCall == nil {
		return nil, invalid("")
	}
	s := &NativeCallStore{contexts: contexts, deps: deps}
	for _, dir := range []string{s.sessionDir(), s.callDir()} {
		if invocationPrivateDir(dir) != nil {
			return nil, invalid("")
		}
	}
	return s, nil
}

func (s *NativeCallStore) sessionDir() string {
	return filepath.Join(s.contexts.dir, "native-skill-sessions")
}
func (s *NativeCallStore) callDir() string {
	return filepath.Join(s.contexts.dir, "native-skill-calls")
}
func (s *NativeCallStore) sessionPath(subject Subject) string {
	return filepath.Join(s.sessionDir(), nativeSessionID(subject)+".json")
}
func (s *NativeCallStore) callPath(subject Subject, callID string) string {
	return filepath.Join(s.callDir(), nativeCallID(subject, callID)+".json")
}

func (s *NativeCallStore) liveAgent(subject Subject, ref AuthorityRef, now time.Time) (*grant.Grant, time.Time, error) {
	fail := func() (*grant.Grant, time.Time, error) {
		return nil, time.Time{}, invalid("native_skill_agent_changed")
	}
	i, err := s.contexts.deps.ReadInstance(subject.InstanceID)
	if err != nil || i.InstanceID != subject.InstanceID || i.AgentID != subject.AgentID || i.Platform != subject.Platform || i.GrantRef.GrantID != ref.GrantID {
		return fail()
	}
	g, err := s.contexts.snapshotGrant(ref.GrantID, now)
	if err != nil || g.Skill != nil || (g.Status != "deployed" && g.Status != "effective") || g.Subject.Type != "agent_instance" ||
		g.Subject.ID != subject.AgentID || g.Platform != subject.Platform {
		return fail()
	}
	d, err := GrantDigest(g)
	if err != nil || d != ref.GrantDigest {
		return fail()
	}
	until, err := s.contexts.deps.SessionBound(subject.Platform, subject.AgentID, subject.SessionID, g.GrantID)
	if err != nil || !now.Before(until) {
		return fail()
	}
	return g, until, nil
}

func (s *NativeCallStore) sessionLive(session *NativeSession, now time.Time) (*grant.Grant, time.Time, error) {
	g, until, err := s.liveAgent(session.Subject, session.AgentAuthority, now)
	if err != nil {
		return nil, time.Time{}, err
	}
	hostUntil, err := s.deps.ValidateSession(*session)
	if err != nil || !now.Before(hostUntil) {
		return nil, time.Time{}, invalid("native_skill_session_unverified")
	}
	if hostUntil.Before(until) {
		until = hostUntil
	}
	return g, until, nil
}

func (s *NativeCallStore) readSession(subject Subject, now time.Time) (*NativeSession, *grant.Grant, error) {
	var session NativeSession
	if readInvocationJSON(s.sessionPath(subject), &session) != nil || session.Subject != sessionSubject(subject) || session.Validate() != nil ||
		signing.VerifyWithSchema(session.SigningSchema, s.contexts.deps.Key.Public(), nativeUnsigned(session), session.Signature) != nil {
		return nil, nil, invalid("native_skill_session_invalid")
	}
	g, until, err := s.sessionLive(&session, now)
	if err != nil || !nativeCurrent(session.nativeSigned, now, until) {
		return nil, nil, invalid("native_skill_session_invalid")
	}
	return &session, g, nil
}

func (s *NativeCallStore) RegisterSession(req NativeSessionRequest) (*NativeSession, error) {
	mu.Lock()
	defer mu.Unlock()
	if !instancePattern.MatchString(req.InstanceID) || !textValid(req.SessionID, 256) || req.TTL <= 0 || req.TTL > MaxTTL {
		return nil, invalid("")
	}
	now := s.contexts.deps.Now().UTC()
	inst, err := s.contexts.deps.ReadInstance(req.InstanceID)
	if err != nil {
		return nil, invalid("")
	}
	g, err := s.contexts.snapshotGrant(inst.GrantRef.GrantID, now)
	if err != nil {
		return nil, err
	}
	d, err := GrantDigest(g)
	if err != nil {
		return nil, err
	}
	c := &NativeSession{nativeSigned: nativeSigned{SchemaVersion: NativeSessionSchema, IssuerID: Issuer,
		Subject:        Subject{Platform: inst.Platform, InstanceID: req.InstanceID, AgentID: inst.AgentID, SessionID: req.SessionID},
		AgentAuthority: AuthorityRef{GrantID: g.GrantID, GrantDigest: d}, IssuedAt: now.Format(time.RFC3339Nano),
		ExpiresAt: now.Add(req.TTL).Format(time.RFC3339Nano), SigningSchema: signing.SchemaLocalCanonicalV1}, RuntimeArtifactSHA256: req.RuntimeArtifactSHA256}
	c.RegistrationID = nativeSessionID(c.Subject)
	if c.Validate() != nil {
		return nil, invalid("")
	}
	_, until, err := s.sessionLive(c, now)
	if err != nil {
		return nil, err
	}
	clampNativeExpiry(&c.nativeSigned, until)
	p := s.sessionPath(c.Subject)
	var old NativeSession
	if err := readInvocationJSON(p, &old); err == nil {
		if !nativeReplayEqual(c, &old, &c.nativeSigned, old.nativeSigned) {
			return nil, invalid("native_skill_session_conflict")
		}
		verified, _, err := s.readSession(c.Subject, now)
		return verified, err
	} else if !errors.Is(err, os.ErrNotExist) {
		return nil, invalid("")
	}
	if err := nativeCapacity(s.sessionDir(), "nsess-", maxNativeSessions); err != nil {
		return nil, err
	}
	c.Signature, err = s.contexts.deps.Key.SignCanonical(nativeUnsigned(c))
	if err != nil {
		return nil, invalid("")
	}
	if err := s.contexts.publish("native_skill_session_attempt", p, c.RegistrationID, c); err != nil {
		return nil, err
	}
	return c, nil
}

func clampNativeExpiry(c *nativeSigned, until time.Time) {
	expires, _ := time.Parse(time.RFC3339Nano, c.ExpiresAt)
	if until.Before(expires) {
		c.ExpiresAt = until.UTC().Format(time.RFC3339Nano)
	}
}

// Used only on an unpublished candidate. Its original lifetime is discarded on
// a duplicate, and the returned record still goes through full live validation.
func nativeReplayEqual(candidate, old any, fields *nativeSigned, previous nativeSigned) bool {
	fields.IssuedAt, fields.ExpiresAt, fields.Signature = previous.IssuedAt, previous.ExpiresAt, previous.Signature
	a, _ := json.Marshal(candidate)
	b, _ := json.Marshal(old)
	return string(a) == string(b)
}

func (s *NativeCallStore) callLive(c *NativeCall, now time.Time) (*NativeCallVerification, time.Time, error) {
	session, g, err := s.readSession(c.Subject, now)
	if err != nil || c.AgentAuthority != session.AgentAuthority || c.SessionRef != (NativeSessionRef{RegistrationID: session.RegistrationID, Signature: session.Signature}) {
		return nil, time.Time{}, invalid("native_skill_session_changed")
	}
	until, _ := time.Parse(time.RFC3339Nano, session.ExpiresAt)
	v := &NativeCallVerification{Call: c, Session: session, AgentGrant: g}
	if c.Context != nil {
		iv, err := s.contexts.verify(c.Context.ContextID, c.Subject, now)
		if err != nil || iv.Contexts[0].Signature != c.Context.Signature || iv.Contexts[0].AgentAuthority != c.AgentAuthority {
			return nil, time.Time{}, invalid("native_skill_context_changed")
		}
		for _, context := range iv.Contexts {
			if context.Loader.RuntimeArtifactSHA256 != session.RuntimeArtifactSHA256 {
				return nil, time.Time{}, invalid("native_skill_runtime_changed")
			}
		}
		end, _ := time.Parse(time.RFC3339Nano, iv.Contexts[0].ExpiresAt)
		if end.Before(until) {
			until = end
		}
		v.Invocation = iv
	}
	hostUntil, err := s.deps.ValidateCall(*c)
	if err != nil || !now.Before(hostUntil) {
		return nil, time.Time{}, invalid("native_skill_call_unverified")
	}
	if hostUntil.Before(until) {
		until = hostUntil
	}
	return v, until, nil
}

func nativeRequestBinding(req NativeCallRequest) (string, error) {
	if !validNativeSubject(req.Subject, true) || !textValid(req.Tool, 128) || !textValid(req.ToolCallID, 256) || req.Params == nil {
		return "", invalid("native_skill_call_invalid")
	}
	// Bound canonicalization and reject cycles/non-JSON objects before entering
	// the shared signer. The runtime HTTP ingress applies its own body bound.
	encoded, err := json.Marshal(req.Params)
	if err != nil || len(encoded) > 1<<20 {
		return "", invalid("native_skill_call_invalid")
	}
	return CallBinding(req.Subject.Platform, req.Subject.SessionID, req.Subject.AgentID, req.Subject.TaskID, req.Tool, req.ToolCallID, req.Params)
}

func (s *NativeCallStore) BindCall(req NativeCallRequest) (*NativeCall, error) {
	mu.Lock()
	defer mu.Unlock()
	binding, err := nativeRequestBinding(req)
	if err != nil || req.TTL <= 0 || req.TTL > NativeCallMaxTTL || req.NoSkill != (req.Context == nil) {
		return nil, invalid("native_skill_call_invalid")
	}
	now := s.contexts.deps.Now().UTC()
	session, _, err := s.readSession(req.Subject, now)
	if err != nil {
		return nil, err
	}
	c := &NativeCall{nativeSigned: nativeSigned{SchemaVersion: NativeCallSchema, IssuerID: Issuer, Subject: req.Subject, AgentAuthority: session.AgentAuthority,
		IssuedAt: now.Format(time.RFC3339Nano), ExpiresAt: now.Add(req.TTL).Format(time.RFC3339Nano), SigningSchema: signing.SchemaLocalCanonicalV1},
		CallID: nativeCallID(req.Subject, req.ToolCallID), SessionRef: NativeSessionRef{RegistrationID: session.RegistrationID, Signature: session.Signature},
		Tool: req.Tool, ToolCallID: req.ToolCallID, RequestBinding: binding, NoSkill: req.NoSkill}
	if req.Context != nil {
		ref := *req.Context
		c.Context = &ref
	}
	if c.Validate() != nil {
		return nil, invalid("")
	}
	_, until, err := s.callLive(c, now)
	if err != nil {
		return nil, err
	}
	clampNativeExpiry(&c.nativeSigned, until)
	p := s.callPath(req.Subject, req.ToolCallID)
	var old NativeCall
	if err := readInvocationJSON(p, &old); err == nil {
		if !nativeReplayEqual(c, &old, &c.nativeSigned, old.nativeSigned) {
			return nil, invalid("native_skill_call_conflict")
		}
		v, err := s.verifyCall(req, now)
		if err != nil {
			return nil, err
		}
		return v.Call, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return nil, invalid("")
	}
	if err := nativeCapacity(s.callDir(), "ncall-", maxNativeCalls); err != nil {
		return nil, err
	}
	c.Signature, err = s.contexts.deps.Key.SignCanonical(nativeUnsigned(c))
	if err != nil {
		return nil, invalid("")
	}
	if err := s.contexts.publish("native_skill_call_attempt", p, c.CallID, c); err != nil {
		return nil, err
	}
	return c, nil
}

// VerifyCall selects only by the full actual call. No request Context/NoSkill
// claim is used to select authority. Missing records are hard failures; callers
// must not convert these errors into an ordinary-Agent fallback.
func (s *NativeCallStore) VerifyCall(req NativeCallRequest) (*NativeCallVerification, error) {
	mu.RLock()
	defer mu.RUnlock()
	return s.verifyCall(req, s.contexts.deps.Now())
}

func (s *NativeCallStore) verifyCall(req NativeCallRequest, now time.Time) (*NativeCallVerification, error) {
	binding, err := nativeRequestBinding(req)
	if err != nil {
		return nil, err
	}
	var c NativeCall
	if readInvocationJSON(s.callPath(req.Subject, req.ToolCallID), &c) != nil || c.Validate() != nil || c.Subject != req.Subject ||
		c.Tool != req.Tool || c.ToolCallID != req.ToolCallID || c.RequestBinding != binding ||
		signing.VerifyWithSchema(c.SigningSchema, s.contexts.deps.Key.Public(), nativeUnsigned(c), c.Signature) != nil {
		return nil, invalid("native_skill_call_invalid")
	}
	v, until, err := s.callLive(&c, now)
	if err != nil || !nativeCurrent(c.nativeSigned, now, until) {
		return nil, invalid("native_skill_call_invalid")
	}
	return v, nil
}

func nativeCapacity(dir, prefix string, limit int) error {
	if invocationAncestors(dir) != nil {
		return invalid("")
	}
	f, err := statefs.Open(dir)
	if err != nil {
		return invalid("")
	}
	defer f.Close()
	entries, err := f.ReadDir(limit + 1)
	if (err != nil && err != io.EOF) || len(entries) >= limit {
		return invalid("native_skill_capacity")
	}
	for _, e := range entries {
		if strings.HasPrefix(e.Name(), ".skill-invocation-") {
			continue
		}
		id, ok := strings.CutSuffix(e.Name(), ".json")
		if !ok || !strings.HasPrefix(id, prefix) || !e.Type().IsRegular() {
			return invalid("")
		}
		part := strings.TrimPrefix(id, prefix)
		if len(part) != 32 || !contextIDPattern.MatchString("sec-"+part) {
			return invalid("")
		}
	}
	return nil
}
