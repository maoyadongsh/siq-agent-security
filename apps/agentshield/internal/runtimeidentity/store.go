// Package runtimeidentity owns signed personal-instance credential authority.
// It does not imply that the host installed a hook or loaded a particular Skill.
package runtimeidentity

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/signing"
)

const maxIdentities = 512

var identityID = regexp.MustCompile(`^ri-[a-f0-9]{32}$`)
var instanceID = regexp.MustCompile(`^hi-[a-f0-9]{32}$`)
var hexDigest = regexp.MustCompile(`^[a-f0-9]{64}$`)

// All Store handles in this process serialize authority writes. The daemon's
// existing state-writer lock supplies cross-process exclusion.
var writeMu sync.RWMutex

var ErrNoTools = errors.New("runtime_identity_no_tools")

var ErrInvalid = errors.New("runtime_identity_invalid")
var ErrConflict = errors.New("runtime_identity_conflict")
var ErrUnavailable = errors.New("runtime_identity_unavailable")

// Record is private signed storage metadata, not an HTTP response DTO.
type Record struct {
	SchemaVersion     string                `json:"schema_version"`
	IdentityID        string                `json:"identity_id"`
	InstanceID        string                `json:"instance_id"`
	AgentID           string                `json:"agent_id"`
	Platform          string                `json:"platform"`
	GrantRef          intent.GrantReference `json:"grant_ref"`
	ActorID           string                `json:"actor_id"`
	CreatedAt         string                `json:"created_at"`
	SessionTTLSeconds int                   `json:"session_ttl_seconds"`
	CredentialHash    string                `json:"credential_hash"`
	Signature         string                `json:"signature"`
}

type Revocation struct {
	SchemaVersion  string `json:"schema_version"`
	IdentityID     string `json:"identity_id"`
	IdentityDigest string `json:"identity_digest"`
	ActorID        string `json:"actor_id"`
	RevokedAt      string `json:"revoked_at"`
	Signature      string `json:"signature"`
}

type CreateRequest struct {
	SchemaVersion         string `json:"schema_version"`
	InstanceID            string `json:"instance_id"`
	GrantID               string `json:"grant_id"`
	ExpectedGrantRevision int    `json:"expected_grant_revision"`
	ActorID               string `json:"actor_id"`
	SessionTTLSeconds     int    `json:"session_ttl_seconds"`
}

// ResolveInstance must resolve the ID against current discovered Hermes roots;
// it must not accept an arbitrary client-provided path.
type ResolveInstance func(string) error

type Store struct {
	dir     string
	key     *signing.Key
	intents *intent.Store
	resolve ResolveInstance
}

func Open(dir string, key *signing.Key, intents *intent.Store, resolve ResolveInstance) (*Store, error) {
	if !filepath.IsAbs(dir) || key == nil || intents == nil || resolve == nil {
		return nil, ErrInvalid
	}
	dir = filepath.Clean(dir)
	for _, name := range []string{"runtime-identities", "runtime-identity-secrets", "runtime-identity-revocations"} {
		if err := privateDir(filepath.Join(dir, name)); err != nil {
			return nil, ErrUnavailable
		}
	}
	return &Store{dir: dir, key: key, intents: intents, resolve: resolve}, nil
}

func AgentID(id string) (string, error) {
	if !instanceID.MatchString(id) {
		return "", ErrInvalid
	}
	return "hri-" + strings.TrimPrefix(id, "hi-"), nil
}
func textValid(s string, max int) bool {
	return utf8.ValidString(s) && strings.TrimSpace(s) != "" && utf8.RuneCountInString(s) <= max && strings.IndexFunc(s, unicode.IsControl) < 0
}
func hash(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }
func unsigned(v any) (map[string]any, error) {
	b, err := json.Marshal(v)
	if err != nil {
		return nil, ErrInvalid
	}
	decoded, err := canon.Decode(b)
	if err != nil {
		return nil, ErrInvalid
	}
	m, ok := decoded.(map[string]any)
	if !ok {
		return nil, ErrInvalid
	}
	delete(m, "signature")
	return m, nil
}
func (s *Store) sign(v any) (string, error) {
	m, err := unsigned(v)
	if err != nil {
		return "", err
	}
	return s.key.SignCanonical(m)
}
func (s *Store) verify(v any, sig string) bool {
	m, err := unsigned(v)
	return err == nil && signing.VerifyCanonical(s.key.Public(), m, sig)
}
func recordDigest(r Record) string {
	m, _ := unsigned(r)
	b, _ := canon.Marshal(m)
	return hash(b)
}
func (s *Store) recordPath(id string) string {
	return filepath.Join(s.dir, "runtime-identities", id+".json")
}
func (s *Store) revokedPath(id string) string {
	return filepath.Join(s.dir, "runtime-identity-revocations", id+".json")
}

// CredentialPath is for installer configuration only; it never reads the token.
func (s *Store) CredentialPath(id string) (string, error) {
	if !identityID.MatchString(id) {
		return "", ErrInvalid
	}
	return filepath.Join(s.dir, "runtime-identity-secrets", id+".token"), nil
}
func (s *Store) read(id string) (Record, error) {
	var r Record
	if !identityID.MatchString(id) {
		return r, ErrInvalid
	}
	if err := readJSON(s.recordPath(id), &r); err != nil {
		return r, ErrUnavailable
	}
	agent, err := AgentID(r.InstanceID)
	_, timeErr := time.Parse(time.RFC3339Nano, r.CreatedAt)
	if err != nil || timeErr != nil || r.SchemaVersion != "local-runtime-identity/v1" || r.IdentityID != id || r.AgentID != agent || r.Platform != "hermes" || !textValid(r.ActorID, 128) || !textValid(r.GrantRef.GrantID, 256) || !textValid(r.GrantRef.AdmissionID, 256) || !hexDigest.MatchString(r.GrantRef.PermissionDigest) || !hexDigest.MatchString(r.CredentialHash) || r.SessionTTLSeconds < 60 || r.SessionTTLSeconds > 86400 || !s.verify(r, r.Signature) {
		return Record{}, ErrInvalid
	}
	return r, nil
}
func (s *Store) revoked(r Record) (bool, error) {
	var rev Revocation
	err := readJSON(s.revokedPath(r.IdentityID), &rev)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, ErrUnavailable
	}
	at, e := time.Parse(time.RFC3339Nano, rev.RevokedAt)
	created, _ := time.Parse(time.RFC3339Nano, r.CreatedAt)
	if e != nil || at.Before(created) || rev.SchemaVersion != "local-runtime-identity-revocation/v1" || rev.IdentityID != r.IdentityID || rev.IdentityDigest != recordDigest(r) || !textValid(rev.ActorID, 128) || !s.verify(rev, rev.Signature) {
		return false, ErrInvalid
	}
	return true, nil
}

// Create publishes the secret first and the signed authority/audit last.
// An interrupted issuance can leave an orphan secret, which cannot authenticate.
// The caller must hold the existing daemon state-writer lock.
func (s *Store) Create(req CreateRequest) (Record, error) {
	writeMu.Lock()
	defer writeMu.Unlock()
	agent, err := AgentID(req.InstanceID)
	if err != nil || req.SchemaVersion != "local-runtime-identity-create/v1" || !textValid(req.GrantID, 256) || req.ExpectedGrantRevision < 0 || !textValid(req.ActorID, 128) || req.SessionTTLSeconds < 60 || req.SessionTTLSeconds > 86400 {
		return Record{}, ErrInvalid
	}
	if s.resolve(req.InstanceID) != nil {
		return Record{}, ErrUnavailable
	}
	ref, err := s.intents.SelectGrant(req.GrantID, "hermes", agent, req.ExpectedGrantRevision)
	if err != nil {
		return Record{}, err
	}
	g, err := s.intents.GrantForReference(ref, "hermes", agent)
	if err != nil {
		return Record{}, err
	}
	allow, approval := grant.RuntimeToolSets(g)
	if len(allow)+len(approval) == 0 {
		return Record{}, ErrNoTools
	}
	ids, err := recordIDs(filepath.Join(s.dir, "runtime-identities"), maxIdentities)
	if err != nil {
		return Record{}, ErrUnavailable
	}
	if len(ids) >= maxIdentities {
		return Record{}, ErrUnavailable
	}
	for _, id := range ids {
		old, e := s.read(id)
		if e != nil {
			return Record{}, e
		}
		revoked, e := s.revoked(old)
		if e != nil {
			return Record{}, e
		}
		if old.InstanceID == req.InstanceID && !revoked {
			return Record{}, ErrConflict
		}
	}
	nonce := make([]byte, 48)
	if _, err = rand.Read(nonce); err != nil {
		return Record{}, ErrUnavailable
	}
	id := "ri-" + hex.EncodeToString(nonce[:16])
	token := id + "." + hex.EncodeToString(nonce[16:])
	r := Record{SchemaVersion: "local-runtime-identity/v1", IdentityID: id, InstanceID: req.InstanceID, AgentID: agent, Platform: "hermes", GrantRef: ref, ActorID: req.ActorID, CreatedAt: time.Now().UTC().Format(time.RFC3339Nano), SessionTTLSeconds: req.SessionTTLSeconds, CredentialHash: hash([]byte(token))}
	r.Signature, err = s.sign(r)
	if err != nil {
		return Record{}, ErrUnavailable
	}
	secretPath, _ := s.CredentialPath(id)
	if err = publish(secretPath, []byte(token)); err != nil {
		return Record{}, ErrUnavailable
	}
	// Never remove a failed publication's orphan here: it may be required to
	// diagnose interruption, and without the signed record it has no authority.
	if _, err = s.intents.GrantForReference(ref, "hermes", agent); err != nil {
		return Record{}, err
	}
	if s.resolve(req.InstanceID) != nil {
		return Record{}, ErrUnavailable
	}
	b, err := json.Marshal(r)
	if err != nil {
		return Record{}, ErrInvalid
	}
	if err = publish(s.recordPath(id), b); err != nil {
		return Record{}, ErrUnavailable
	}
	return r, nil
}

// Authenticate rereads signed metadata, revocation, and Grant on every call.
// It does not authorize a session: the decision middleware must additionally
// match the session's signed binding to this identity and fixed Grant.
func (s *Store) Authenticate(token string) (Record, error) {
	writeMu.RLock()
	defer writeMu.RUnlock()
	return s.authenticate(token)
}

func (s *Store) authenticate(token string) (Record, error) {
	if len(token) != 100 || token[35] != '.' || !identityID.MatchString(token[:35]) || !hexDigest.MatchString(token[36:]) {
		return Record{}, ErrInvalid
	}
	r, err := s.read(token[:35])
	if err != nil {
		return Record{}, ErrUnavailable
	}
	supplied := hash([]byte(token))
	if subtle.ConstantTimeCompare([]byte(supplied), []byte(r.CredentialHash)) != 1 {
		return Record{}, ErrUnavailable
	}
	revoked, err := s.revoked(r)
	if err != nil || revoked {
		return Record{}, ErrUnavailable
	}
	if _, err = s.intents.GrantForReference(r.GrantRef, r.Platform, r.AgentID); err != nil {
		return Record{}, ErrUnavailable
	}
	return r, nil
}

// Revoke remains available even after a Grant expires or an instance disappears.
// Retrying is idempotent and retains the original actor and signed audit record.
func (s *Store) Revoke(id, actor string) (Revocation, error) {
	writeMu.Lock()
	defer writeMu.Unlock()
	if !identityID.MatchString(id) || !textValid(actor, 128) {
		return Revocation{}, ErrInvalid
	}
	r, err := s.read(id)
	if err != nil {
		return Revocation{}, err
	}
	revoked, err := s.revoked(r)
	if err != nil {
		return Revocation{}, err
	}
	if revoked {
		var existing Revocation
		err = readJSON(s.revokedPath(id), &existing)
		return existing, err
	}
	rev := Revocation{SchemaVersion: "local-runtime-identity-revocation/v1", IdentityID: id, IdentityDigest: recordDigest(r), ActorID: actor, RevokedAt: time.Now().UTC().Format(time.RFC3339Nano)}
	rev.Signature, err = s.sign(rev)
	if err != nil {
		return Revocation{}, ErrUnavailable
	}
	b, err := json.Marshal(rev)
	if err != nil {
		return Revocation{}, ErrInvalid
	}
	if err = publish(s.revokedPath(id), b); err != nil {
		return Revocation{}, ErrUnavailable
	}
	return rev, nil
}
