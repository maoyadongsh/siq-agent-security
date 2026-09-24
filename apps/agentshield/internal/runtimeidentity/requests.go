package runtimeidentity

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

var requestID = regexp.MustCompile(`^qwen-request-[a-f0-9]{16}$`)
var requestScopeID = regexp.MustCompile(`^[a-f0-9]{24}$`)

type RequestIssuerCreate struct {
	SchemaVersion      string `json:"schema_version"`
	ParentIdentityID   string `json:"parent_identity_id"`
	ScopeID            string `json:"scope_id"`
	MaxIdentitySeconds int    `json:"max_identity_seconds"`
	ExpiresAt          string `json:"expires_at"`
	ActorID            string `json:"actor_id"`
}

type RequestIssuer struct {
	SchemaVersion      string `json:"schema_version"`
	ParentIdentityID   string `json:"parent_identity_id"`
	ParentSHA256       string `json:"parent_sha256"`
	ScopeID            string `json:"scope_id"`
	MaxIdentitySeconds int    `json:"max_identity_seconds"`
	ExpiresAt          string `json:"expires_at"`
	ActorID            string `json:"actor_id"`
	CreatedAt          string `json:"created_at"`
	Signature          string `json:"signature,omitempty"`
}

type RequestScope struct {
	ParentIdentityID string `json:"parent_identity_id"`
	ParentSHA256     string `json:"parent_sha256"`
	IssuerSHA256     string `json:"issuer_sha256"`
	ScopeID          string `json:"scope_id"`
	RequestID        string `json:"request_id"`
	ExecutionSHA256  string `json:"execution_sha256"`
	SessionNamespace string `json:"session_namespace"`
	ExpiresAt        string `json:"expires_at"`
}

type RequestIdentityCreate struct {
	SchemaVersion   string `json:"schema_version"`
	RequestID       string `json:"request_id"`
	ExecutionSHA256 string `json:"execution_sha256"`
	ExpiresAt       string `json:"expires_at"`
}

type RequestIdentityCancel struct {
	SchemaVersion   string `json:"schema_version"`
	RequestID       string `json:"request_id"`
	ExecutionSHA256 string `json:"execution_sha256"`
}

type requestAttempt struct {
	SchemaVersion string       `json:"schema_version"`
	IdentityID    string       `json:"identity_id"`
	CreatedAt     string       `json:"created_at"`
	Request       RequestScope `json:"request"`
	Signature     string       `json:"signature"`
}

type requestCancellation struct {
	SchemaVersion    string `json:"schema_version"`
	IdentityID       string `json:"identity_id"`
	ParentIdentityID string `json:"parent_identity_id"`
	RequestID        string `json:"request_id"`
	ExecutionSHA256  string `json:"execution_sha256"`
	CancelledAt      string `json:"cancelled_at"`
	Signature        string `json:"signature"`
}

func requestTime(value string) (time.Time, bool) {
	t, err := time.Parse(time.RFC3339, value)
	return t, err == nil && value == t.UTC().Format(time.RFC3339)
}

func requestNamespace(scope, run string) string {
	return "siq:openshell:pool:" + scope + ":" + run + ":siq_analysis"
}

func requestIdentityID(parent, run string) string {
	return "ri-" + hash([]byte("siq.runtime-request/v1\x00" + parent + "\x00" + run))[:32]
}

func validRequestScope(v *RequestScope) bool {
	if v == nil {
		return false
	}
	_, validTime := requestTime(v.ExpiresAt)
	return identityID.MatchString(v.ParentIdentityID) && hexDigest.MatchString(v.ParentSHA256) &&
		hexDigest.MatchString(v.IssuerSHA256) && requestScopeID.MatchString(v.ScopeID) &&
		requestID.MatchString(v.RequestID) && hexDigest.MatchString(v.ExecutionSHA256) && validTime &&
		v.SessionNamespace == requestNamespace(v.ScopeID, v.RequestID)
}

func (s *Store) requestPath(kind, id string) string { return filepath.Join(s.dir, kind, id+".json") }

func (s *Store) publishSigned(path string, value any) error {
	b, err := json.Marshal(value)
	if err != nil {
		return ErrInvalid
	}
	if publish(path, b) != nil {
		return ErrUnavailable
	}
	return nil
}

func (s *Store) issuer(parent Record) (RequestIssuer, error) {
	var v RequestIssuer
	if parent.RequestScope != nil || parent.Platform != "hermes" || parent.SchemaVersion != "local-runtime-identity/v1" ||
		readJSON(s.requestPath("runtime-request-issuers", parent.IdentityID), &v) != nil {
		return v, ErrUnavailable
	}
	created, validCreated := requestTime(v.CreatedAt)
	expires, validExpires := requestTime(v.ExpiresAt)
	if v.SchemaVersion != "local-runtime-request-issuer/v1" || v.ParentIdentityID != parent.IdentityID ||
		v.ParentSHA256 != recordDigest(parent) || !requestScopeID.MatchString(v.ScopeID) ||
		v.MaxIdentitySeconds < 60 || v.MaxIdentitySeconds > 3600 || !textValid(v.ActorID, 128) ||
		!validCreated || !validExpires || !expires.After(created) || expires.Sub(created) > 24*time.Hour || !s.verify(v, v.Signature) {
		return v, ErrInvalid
	}
	return v, nil
}

// EnableRequestIssuer is management-only. It never approves or expands Grant.
func (s *Store) EnableRequestIssuer(req RequestIssuerCreate) (RequestIssuer, error) {
	writeMu.Lock()
	defer writeMu.Unlock()
	expires, validTime := requestTime(req.ExpiresAt)
	now := time.Now().UTC().Truncate(time.Second)
	if req.SchemaVersion != "local-runtime-request-issuer-create/v1" || !identityID.MatchString(req.ParentIdentityID) ||
		!requestScopeID.MatchString(req.ScopeID) || req.MaxIdentitySeconds < 60 || req.MaxIdentitySeconds > 3600 ||
		!textValid(req.ActorID, 128) || !validTime || !expires.After(now) || expires.Sub(now) > 24*time.Hour {
		return RequestIssuer{}, ErrInvalid
	}
	parent, err := s.read(req.ParentIdentityID)
	if err != nil || parent.RequestScope != nil || parent.SchemaVersion != "local-runtime-identity/v1" || parent.Platform != "hermes" {
		return RequestIssuer{}, ErrInvalid
	}
	if revoked, e := s.revoked(parent); e != nil || revoked {
		return RequestIssuer{}, ErrUnavailable
	}
	if platform, e := s.resolve(parent.InstanceID); e != nil || platform != parent.Platform {
		return RequestIssuer{}, ErrUnavailable
	}
	g, err := s.intents.GrantForReference(parent.GrantRef, parent.Platform, parent.AgentID)
	if err != nil {
		return RequestIssuer{}, ErrUnavailable
	}
	if g.ExpiresAt != nil {
		end, e := time.Parse(time.RFC3339Nano, *g.ExpiresAt)
		if e != nil || expires.After(end) {
			return RequestIssuer{}, ErrInvalid
		}
	}
	want := RequestIssuer{SchemaVersion: "local-runtime-request-issuer/v1", ParentIdentityID: parent.IdentityID,
		ParentSHA256: recordDigest(parent), ScopeID: req.ScopeID, MaxIdentitySeconds: req.MaxIdentitySeconds,
		ExpiresAt: req.ExpiresAt, ActorID: req.ActorID, CreatedAt: now.Format(time.RFC3339)}
	path := s.requestPath("runtime-request-issuers", parent.IdentityID)
	if _, e := os.Lstat(path); e == nil {
		prior, e := s.issuer(parent)
		if e != nil {
			return RequestIssuer{}, e
		}
		want.CreatedAt, want.Signature = prior.CreatedAt, prior.Signature
		if want != prior {
			return RequestIssuer{}, ErrConflict
		}
		return prior, nil
	} else if !errors.Is(e, os.ErrNotExist) {
		return RequestIssuer{}, ErrUnavailable
	}
	want.Signature, err = s.sign(want)
	if err != nil {
		return RequestIssuer{}, err
	}
	if _, err = s.intents.GrantForReference(parent.GrantRef, parent.Platform, parent.AgentID); err != nil {
		return RequestIssuer{}, ErrUnavailable
	}
	if platform, e := s.resolve(parent.InstanceID); e != nil || platform != parent.Platform {
		return RequestIssuer{}, ErrUnavailable
	}
	return want, s.publishSigned(path, want)
}

func (s *Store) requestCancelled(parent, run, execution string) (bool, error) {
	id := requestIdentityID(parent, run)
	var v requestCancellation
	err := readJSON(s.requestPath("runtime-request-cancellations", id), &v)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	_, validTime := requestTime(v.CancelledAt)
	if err != nil || v.SchemaVersion != "local-runtime-request-cancellation/v1" || v.IdentityID != id ||
		v.ParentIdentityID != parent || v.RequestID != run || v.ExecutionSHA256 != execution || !validTime || !s.verify(v, v.Signature) {
		return false, ErrUnavailable
	}
	return true, nil
}

// No token or execution authority is reconstructed from this metadata check.
func (s *Store) checkRequestRecord(r Record) error {
	if r.RequestScope == nil {
		return nil
	}
	v := r.RequestScope
	if !validRequestScope(v) || r.IdentityID != requestIdentityID(v.ParentIdentityID, v.RequestID) {
		return ErrInvalid
	}
	parent, err := s.read(v.ParentIdentityID)
	if err != nil || parent.RequestScope != nil || recordDigest(parent) != v.ParentSHA256 ||
		parent.InstanceID != r.InstanceID || parent.AgentID != r.AgentID || parent.GrantRef != r.GrantRef || parent.ActorID != r.ActorID ||
		r.SessionTTLSeconds > parent.SessionTTLSeconds {
		return ErrUnavailable
	}
	if revoked, e := s.revoked(parent); e != nil || revoked {
		return ErrUnavailable
	}
	issuer, err := s.issuer(parent)
	if err != nil || issuer.ScopeID != v.ScopeID || recordIssuerDigest(issuer) != v.IssuerSHA256 || r.SessionTTLSeconds > issuer.MaxIdentitySeconds {
		return ErrUnavailable
	}
	end, _ := requestTime(v.ExpiresAt)
	capEnd, _ := requestTime(issuer.ExpiresAt)
	created, e := time.Parse(time.RFC3339Nano, r.CreatedAt)
	if e != nil || !end.After(time.Now()) || end.After(capEnd) || !end.After(created) || end.Sub(created) > time.Duration(issuer.MaxIdentitySeconds)*time.Second {
		return ErrUnavailable
	}
	if platform, e := s.resolve(parent.InstanceID); e != nil || platform != r.Platform {
		return ErrUnavailable
	}
	if cancelled, e := s.requestCancelled(parent.IdentityID, v.RequestID, v.ExecutionSHA256); e != nil || cancelled {
		return ErrUnavailable
	}
	return nil
}

func recordIssuerDigest(v RequestIssuer) string {
	m, _ := unsigned(v)
	b, _ := canon.Marshal(m)
	return hash(b)
}

func (s *Store) requestToken(id string) (string, error) {
	path, _ := s.CredentialPath(id)
	if _, err := os.Lstat(path); errors.Is(err, os.ErrNotExist) {
		nonce := make([]byte, 32)
		if _, err = rand.Read(nonce); err != nil {
			return "", ErrUnavailable
		}
		token := id + "." + hex.EncodeToString(nonce)
		if err = publish(path, []byte(token)); err != nil {
			return "", ErrUnavailable
		}
		return token, nil
	} else if err != nil {
		return "", ErrUnavailable
	}
	if checkAncestors(filepath.Dir(path)) != nil {
		return "", ErrUnavailable
	}
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Size() != 100 || (runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0) {
		return "", ErrUnavailable
	}
	f, err := statefs.OpenPrivate(path)
	if err != nil {
		return "", ErrUnavailable
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(info, opened) {
		return "", ErrUnavailable
	}
	raw, err := io.ReadAll(io.LimitReader(f, 101))
	if err != nil || len(raw) != 100 || string(raw[:36]) != id+"." || !hexDigest.Match(raw[36:]) {
		return "", ErrUnavailable
	}
	return string(raw), nil
}

// IssueRequest retries the same signed attempt; cancellation wins permanently.
func (s *Store) IssueRequest(token string, req RequestIdentityCreate) (Record, error) {
	writeMu.Lock()
	defer writeMu.Unlock()
	parent, g, err := s.authenticateWithGrant(token)
	if err != nil {
		return Record{}, ErrCredential
	}
	issuer, err := s.issuer(parent)
	if err != nil {
		return Record{}, err
	}
	expires, validTime := requestTime(req.ExpiresAt)
	capEnd, _ := requestTime(issuer.ExpiresAt)
	now := time.Now().UTC().Truncate(time.Second)
	if req.SchemaVersion != "local-runtime-request-identity-create/v1" || !requestID.MatchString(req.RequestID) || !hexDigest.MatchString(req.ExecutionSHA256) ||
		!validTime || !expires.After(now) || expires.After(capEnd) || expires.Sub(now) > time.Duration(issuer.MaxIdentitySeconds)*time.Second {
		return Record{}, ErrInvalid
	}
	if platform, e := s.resolve(parent.InstanceID); e != nil || platform != parent.Platform {
		return Record{}, ErrUnavailable
	}
	if g.ExpiresAt != nil {
		end, e := time.Parse(time.RFC3339Nano, *g.ExpiresAt)
		if e != nil || expires.After(end) {
			return Record{}, ErrInvalid
		}
	}
	if cancelled, e := s.requestCancelled(parent.IdentityID, req.RequestID, req.ExecutionSHA256); e != nil || cancelled {
		return Record{}, ErrConflict
	}
	id := requestIdentityID(parent.IdentityID, req.RequestID)
	scope := RequestScope{ParentIdentityID: parent.IdentityID, ParentSHA256: recordDigest(parent), IssuerSHA256: recordIssuerDigest(issuer), ScopeID: issuer.ScopeID,
		RequestID: req.RequestID, ExecutionSHA256: req.ExecutionSHA256, SessionNamespace: requestNamespace(issuer.ScopeID, req.RequestID), ExpiresAt: req.ExpiresAt}
	if old, e := s.readRequestIdentity(id); e == nil {
		if old.RequestScope == nil || *old.RequestScope != scope || s.checkRequestRecord(old) != nil {
			return Record{}, ErrConflict
		}
		if revoked, e := s.revoked(old); e != nil || revoked {
			return Record{}, ErrConflict
		}
		// Do not manufacture a replacement token if an issued credential is lost.
		path, _ := s.CredentialPath(old.IdentityID)
		if _, err := os.Lstat(path); err != nil {
			return Record{}, ErrUnavailable
		}
		secret, err := s.requestToken(old.IdentityID)
		if err != nil || hash([]byte(secret)) != old.CredentialHash {
			return Record{}, ErrUnavailable
		}
		return old, nil
	} else if !errors.Is(e, os.ErrNotExist) {
		return Record{}, ErrUnavailable
	}
	ids, e := recordIDs(filepath.Join(s.dir, "runtime-identities"), maxIdentities)
	if e != nil || len(ids) >= maxIdentities {
		return Record{}, ErrUnavailable
	}
	attempt := requestAttempt{SchemaVersion: "local-runtime-request-attempt/v1", IdentityID: id, CreatedAt: now.Format(time.RFC3339), Request: scope}
	path := s.requestPath("runtime-request-attempts", id)
	var prior requestAttempt
	if e = readJSON(path, &prior); e == nil {
		_, valid := requestTime(prior.CreatedAt)
		if prior.SchemaVersion != attempt.SchemaVersion || prior.IdentityID != id || prior.Request != scope || !valid || !s.verify(prior, prior.Signature) {
			return Record{}, ErrConflict
		}
		attempt = prior
	} else if errors.Is(e, os.ErrNotExist) {
		ids, e = recordIDs(filepath.Dir(path), maxIdentities)
		if e != nil || len(ids) >= maxIdentities {
			return Record{}, ErrUnavailable
		}
		attempt.Signature, err = s.sign(attempt)
		if err != nil {
			return Record{}, err
		}
		if err = s.publishSigned(path, attempt); err != nil {
			return Record{}, err
		}
	} else {
		return Record{}, ErrUnavailable
	}
	childToken, err := s.requestToken(id)
	if err != nil {
		return Record{}, err
	}
	ttl := issuer.MaxIdentitySeconds
	if parent.SessionTTLSeconds < ttl {
		ttl = parent.SessionTTLSeconds
	}
	r := Record{SchemaVersion: "local-runtime-identity/v3", IdentityID: id, InstanceID: parent.InstanceID, AgentID: parent.AgentID, Platform: parent.Platform,
		GrantRef: parent.GrantRef, ActorID: parent.ActorID, CreatedAt: attempt.CreatedAt, SessionTTLSeconds: ttl, CredentialHash: hash([]byte(childToken)), RequestScope: &scope}
	if _, _, err = s.authenticateWithGrant(token); err != nil || s.checkRequestRecord(r) != nil {
		return Record{}, ErrUnavailable
	}
	r.Signature, err = s.sign(r)
	if err != nil {
		return Record{}, err
	}
	return r, s.publishSigned(s.recordPath(id), r)
}

// CancelRequest uses possession only: Grant/parent expiry must not block cleanup.
func (s *Store) CancelRequest(token string, req RequestIdentityCancel) (string, bool, error) {
	writeMu.Lock()
	defer writeMu.Unlock()
	parent, err := s.credentialRecord(token)
	if err != nil {
		return "", false, ErrCredential
	}
	if _, err = s.issuer(parent); err != nil {
		return "", false, err
	}
	if req.SchemaVersion != "local-runtime-request-identity-cancel/v1" || !requestID.MatchString(req.RequestID) || !hexDigest.MatchString(req.ExecutionSHA256) {
		return "", false, ErrInvalid
	}
	id := requestIdentityID(parent.IdentityID, req.RequestID)
	r, err := s.readRequestIdentity(id)
	issued := err == nil
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return "", false, ErrUnavailable
	}
	if issued && (r.RequestScope == nil || r.RequestScope.ParentIdentityID != parent.IdentityID || r.RequestScope.RequestID != req.RequestID || r.RequestScope.ExecutionSHA256 != req.ExecutionSHA256) {
		return "", false, ErrConflict
	}
	var attempt requestAttempt
	if e := readJSON(s.requestPath("runtime-request-attempts", id), &attempt); e == nil {
		_, validCreated := requestTime(attempt.CreatedAt)
		if attempt.SchemaVersion != "local-runtime-request-attempt/v1" || !validCreated || !validRequestScope(&attempt.Request) || attempt.Request.ParentSHA256 != recordDigest(parent) || attempt.IdentityID != id || attempt.Request.ParentIdentityID != parent.IdentityID || attempt.Request.RequestID != req.RequestID || attempt.Request.ExecutionSHA256 != req.ExecutionSHA256 || !s.verify(attempt, attempt.Signature) {
			return "", false, ErrConflict
		}
	} else if !errors.Is(e, os.ErrNotExist) {
		return "", false, ErrUnavailable
	}
	cancelled, err := s.requestCancelled(parent.IdentityID, req.RequestID, req.ExecutionSHA256)
	if err != nil {
		return "", false, err
	}
	if !cancelled {
		path := s.requestPath("runtime-request-cancellations", id)
		ids, e := recordIDs(filepath.Dir(path), maxIdentities)
		if e != nil || len(ids) >= maxIdentities {
			return "", false, ErrUnavailable
		}
		v := requestCancellation{SchemaVersion: "local-runtime-request-cancellation/v1", IdentityID: id, ParentIdentityID: parent.IdentityID, RequestID: req.RequestID, ExecutionSHA256: req.ExecutionSHA256, CancelledAt: time.Now().UTC().Format(time.RFC3339)}
		v.Signature, err = s.sign(v)
		if err != nil {
			return "", false, err
		}
		if err = s.publishSigned(path, v); err != nil {
			return "", false, err
		}
	}
	if issued {
		if _, err = s.revokeRecord(r, "runtime-request:"+parent.IdentityID); err != nil {
			return "", false, err
		}
	}
	return id, issued, nil
}

// Absence is distinct from an unreadable or malformed existing authority.
func (s *Store) readRequestIdentity(id string) (Record, error) {
	if !identityID.MatchString(id) {
		return Record{}, ErrInvalid
	}
	if checkAncestors(filepath.Dir(s.recordPath(id))) != nil {
		return Record{}, ErrUnavailable
	}
	if _, err := os.Lstat(s.recordPath(id)); errors.Is(err, os.ErrNotExist) {
		return Record{}, os.ErrNotExist
	} else if err != nil {
		return Record{}, ErrUnavailable
	}
	return s.read(id)
}
