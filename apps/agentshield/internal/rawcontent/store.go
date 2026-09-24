// Package rawcontent owns optional encrypted task content. It is deliberately
// separate from receipts, effect evidence, and audit state.
package rawcontent

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/statefs"
	"strings"
	"sync"
	"time"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/fileopen"
)

const (
	DefaultRetention = 24 * time.Hour
	DefaultBudget    = int64(64 << 20)
	MinRetention     = time.Hour
	MaxRetention     = 30 * 24 * time.Hour
	MinBudget        = int64(1 << 20)
	MaxBudget        = int64(1 << 30)
	MaxPlaintext     = 1 << 20
)

var (
	ErrDisabled     = errors.New("raw_content_disabled")
	ErrInvalid      = errors.New("raw_content_invalid")
	ErrBudget       = errors.New("raw_content_budget_exceeded")
	ErrExpired      = errors.New("raw_content_expired")
	ErrRevoked      = errors.New("raw_content_authorization_revoked")
	ErrConflict     = errors.New("raw_content_authorization_conflict")
	ErrDenied       = errors.New("raw_content_authorization_denied")
	ErrState        = errors.New("raw_content_state_invalid")
	storeMu         sync.Mutex
	random          io.Reader = rand.Reader
	pathPattern               = regexp.MustCompile(`^/(?:[^/~]|~[01])(?:[^/]|/(?:[^/~]|~[01])){0,254}$`)
	secretValue               = regexp.MustCompile(`(?i)(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9._~+/=-]{8,}|\bsk-[A-Za-z0-9_-]{16,}|\bAKIA[A-Z0-9]{16}\b)`)
	recordIDPattern           = regexp.MustCompile(`^raw-[a-f0-9]{32}$`)
)

type Limits struct {
	Retention time.Duration
	Budget    int64
}

func (l Limits) valid() bool {
	return l.Retention >= MinRetention && l.Retention <= MaxRetention && l.Budget >= MinBudget && l.Budget <= MaxBudget
}

type Field struct {
	Path   string `json:"path"`
	Value  string `json:"value"`
	Secret bool   `json:"secret"`
}

type payloadField struct {
	Path  string `json:"path"`
	Value string `json:"value"`
}

type payload struct {
	Schema       string         `json:"schema_version"`
	Kind         string         `json:"kind"`
	Fields       []payloadField `json:"fields"`
	OmittedCount int            `json:"omitted_secret_count"`
}

type Prepared struct{ raw []byte }

func sensitivePath(path string) bool {
	part := path[strings.LastIndex(path, "/")+1:]
	part = strings.ToLower(strings.ReplaceAll(part, "~1", "/"))
	part = strings.ReplaceAll(part, "~0", "~")
	part = strings.ReplaceAll(part, "-", "_")
	for _, name := range []string{"password", "passwd", "secret", "token", "authorization", "cookie", "api_key", "private_key", "credential", "access_key", "refresh_token", "client_secret"} {
		if part == name || strings.HasSuffix(part, "_"+name) {
			return true
		}
	}
	return false
}

func safeText(value string, limit int) bool {
	if value == "" || !utf8.ValidString(value) || len(value) > limit {
		return false
	}
	for _, r := range value {
		if unicode.IsControl(r) && r != '\n' && r != '\t' && r != '\r' {
			return false
		}
	}
	return true
}

// Prepare is the only constructor for plaintext accepted by Authority.Capture.
// Explicitly secret fields and built-in credential shapes are omitted whole.
func Prepare(kind string, fields []Field) (Prepared, error) {
	if kind != "input" && kind != "parameters" && kind != "output" && kind != "note" || len(fields) == 0 || len(fields) > 1024 {
		return Prepared{}, ErrInvalid
	}
	out := payload{Schema: "local-raw-task-content/v1", Kind: kind, Fields: []payloadField{}}
	seen := map[string]bool{}
	for _, field := range fields {
		if !pathPattern.MatchString(field.Path) || seen[field.Path] || !safeText(field.Value, MaxPlaintext) {
			return Prepared{}, ErrInvalid
		}
		seen[field.Path] = true
		if field.Secret || sensitivePath(field.Path) || secretValue.MatchString(field.Value) {
			out.OmittedCount++
			continue
		}
		out.Fields = append(out.Fields, payloadField{Path: field.Path, Value: field.Value})
	}
	if len(out.Fields) == 0 {
		return Prepared{}, ErrInvalid
	}
	raw, err := json.Marshal(out)
	if err != nil || len(raw) > MaxPlaintext {
		return Prepared{}, ErrInvalid
	}
	return Prepared{raw: raw}, nil
}

type Envelope struct {
	Schema        string         `json:"schema_version"`
	RecordID      string         `json:"record_id"`
	TaskRef       string         `json:"task_ref"`
	Kind          string         `json:"kind"`
	CreatedAt     string         `json:"created_at"`
	ExpiresAt     string         `json:"expires_at"`
	PlaintextHash string         `json:"plaintext_sha256"`
	PlaintextSize int            `json:"plaintext_bytes"`
	OmittedCount  int            `json:"omitted_secret_count"`
	Algorithm     string         `json:"algorithm"`
	Nonce         string         `json:"nonce_base64"`
	Ciphertext    string         `json:"ciphertext_base64"`
	Source        *RuntimeSource `json:"source,omitempty"`
}

type Store struct {
	dir    string
	key    []byte
	limits Limits
}

func taskRef(taskID string) (string, bool) {
	if !safeText(taskID, 1024) || strings.TrimSpace(taskID) != taskID || utf8.RuneCountInString(taskID) > 256 {
		return "", false
	}
	for _, r := range taskID {
		if unicode.IsControl(r) {
			return "", false
		}
	}
	sum := sha256.Sum256([]byte(taskID))
	return "sha256:" + hex.EncodeToString(sum[:]), true
}

func keyPath(stateDir string) string    { return filepath.Join(stateDir, "keys", "raw-content.key") }
func contentDir(stateDir string) string { return filepath.Join(stateDir, "raw-task-content") }

// OpenExisting never creates the optional key or content directory.
func OpenExisting(stateDir string, limits Limits) (*Store, error) {
	if stateDir == "" || !limits.valid() {
		return nil, ErrInvalid
	}
	if runtime.GOOS == "windows" {
		if err := statefs.CheckPrivateDir(stateDir); errors.Is(err, os.ErrNotExist) {
			return nil, ErrDisabled
		} else if err != nil {
			return nil, ErrState
		}
	}
	key, err := readKey(keyPath(stateDir))
	if errors.Is(err, os.ErrNotExist) {
		return nil, ErrDisabled
	}
	if err != nil {
		return nil, err
	}
	dir := contentDir(stateDir)
	if err := privateDir(dir); err != nil {
		return nil, err
	}
	return &Store{dir: dir, key: key, limits: limits}, nil
}

// Initialize is reserved for an explicit management enable operation.
func Initialize(stateDir string, limits Limits) (*Store, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	if stateDir == "" || !limits.valid() {
		return nil, ErrInvalid
	}
	if err := statefs.MkdirAllPrivate(stateDir); err != nil {
		return nil, ErrState
	}
	if err := statefs.MkdirAllPrivate(filepath.Join(stateDir, "keys")); err != nil {
		return nil, ErrState
	}
	path := keyPath(stateDir)
	if _, err := os.Lstat(path); errors.Is(err, os.ErrNotExist) {
		key := make([]byte, 32)
		if _, err := io.ReadFull(random, key); err != nil {
			return nil, ErrState
		}
		f, err := statefs.CreatePrivate(path)
		if err != nil {
			return nil, ErrState
		}
		_, writeErr := f.WriteString(base64.StdEncoding.EncodeToString(key))
		syncErr := f.Sync()
		closeErr := f.Close()
		if writeErr != nil || syncErr != nil || closeErr != nil {
			return nil, ErrState
		}
	} else if err != nil {
		return nil, ErrState
	}
	if err := statefs.MkdirAllPrivate(contentDir(stateDir)); err != nil && !errors.Is(err, os.ErrExist) {
		return nil, ErrState
	}
	return OpenExisting(stateDir, limits)
}

func privateDir(path string) error {
	if err := statefs.CheckPrivateDir(path); err != nil {
		return ErrState
	}
	info, err := os.Lstat(path)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || (runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0) {
		return ErrState
	}
	return nil
}

func readKey(path string) ([]byte, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 || info.Size() > 128 || (runtime.GOOS != "windows" && info.Mode().Perm()&0077 != 0) {
		return nil, ErrState
	}
	raw, err := statefs.ReadPrivateFile(path, 128)
	if err != nil {
		return nil, ErrState
	}
	key, err := base64.StdEncoding.Strict().DecodeString(string(raw))
	if err != nil || len(key) != 32 {
		return nil, ErrState
	}
	return key, nil
}

func aad(e Envelope) []byte {
	copy := e
	copy.Nonce, copy.Ciphertext = "", ""
	raw, _ := json.Marshal(copy)
	return raw
}

func (s *Store) checkCachedKey() error {
	if runtime.GOOS != "windows" {
		return nil
	}
	root := filepath.Dir(s.dir)
	if statefs.CheckPrivateDir(root) != nil {
		return ErrState
	}
	current, err := readKey(keyPath(root))
	if err != nil || subtle.ConstantTimeCompare(current, s.key) != 1 {
		return ErrState
	}
	return nil
}

func (s *Store) diskBytes() (int64, error) {
	entries, err := statefs.ReadDir(s.dir)
	if err != nil {
		return 0, ErrState
	}
	var total int64
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".pending-") {
			continue
		}
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			return 0, ErrState
		}
		info, err := entry.Info()
		if err != nil || !info.Mode().IsRegular() {
			return 0, ErrState
		}
		total += info.Size()
	}
	return total, nil
}

// write is intentionally package-private. All production writes must pass
// through Authority.Capture so an initialized store alone cannot capture data.
func (s *Store) write(taskID string, content Prepared, retention time.Duration, now time.Time) (Envelope, error) {
	return s.writeFromRuntime(taskID, content, retention, now, nil)
}

func (s *Store) writeFromRuntime(taskID string, content Prepared, retention time.Duration, now time.Time, source *RuntimeSource) (Envelope, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	if err := s.checkCachedKey(); err != nil {
		return Envelope{}, err
	}
	ref, ok := taskRef(taskID)
	if !ok || now.IsZero() || retention < MinRetention || retention > s.limits.Retention || len(content.raw) == 0 || len(content.raw) > MaxPlaintext || privateDir(s.dir) != nil {
		return Envelope{}, ErrInvalid
	}
	var p payload
	if json.Unmarshal(content.raw, &p) != nil || p.Schema != "local-raw-task-content/v1" ||
		(p.Kind != "input" && p.Kind != "parameters" && p.Kind != "output" && p.Kind != "note") || len(p.Fields) == 0 {
		return Envelope{}, ErrInvalid
	}
	idBytes := make([]byte, 16)
	nonce := make([]byte, 12)
	if _, err := io.ReadFull(random, idBytes); err != nil {
		return Envelope{}, ErrState
	}
	if _, err := io.ReadFull(random, nonce); err != nil {
		return Envelope{}, ErrState
	}
	sum := sha256.Sum256(content.raw)
	e := Envelope{Schema: "local-raw-task-content-envelope/v1", RecordID: "raw-" + hex.EncodeToString(idBytes), TaskRef: ref, Kind: p.Kind, CreatedAt: now.UTC().Format(time.RFC3339Nano), ExpiresAt: now.Add(retention).UTC().Format(time.RFC3339Nano), PlaintextHash: hex.EncodeToString(sum[:]), PlaintextSize: len(content.raw), OmittedCount: p.OmittedCount, Algorithm: "aes-256-gcm/v1", Nonce: base64.StdEncoding.EncodeToString(nonce)}
	if source != nil {
		if !source.valid() {
			return Envelope{}, ErrInvalid
		}
		copy := *source
		e.Schema, e.Source = "local-raw-task-content-envelope/v2", &copy
	}
	block, err := aes.NewCipher(s.key)
	if err != nil {
		return Envelope{}, ErrState
	}
	gcm, _ := cipher.NewGCM(block)
	e.Ciphertext = base64.StdEncoding.EncodeToString(gcm.Seal(nil, nonce, content.raw, aad(e)))
	raw, _ := json.MarshalIndent(e, "", "  ")
	used, err := s.diskBytes()
	if err != nil {
		return Envelope{}, err
	}
	if used+int64(len(raw)) > s.limits.Budget {
		return Envelope{}, ErrBudget
	}
	path := filepath.Join(s.dir, e.RecordID+".json")
	f, err := statefs.CreatePrivateTemp(s.dir, ".pending-content-*")
	if err != nil {
		return Envelope{}, ErrState
	}
	defer statefs.Remove(f.Name())
	_, writeErr := f.Write(raw)
	syncErr := f.Sync()
	closeErr := f.Close()
	if writeErr != nil || syncErr != nil || closeErr != nil {
		return Envelope{}, ErrState
	}
	if err := statefs.Link(f.Name(), path); err != nil {
		return Envelope{}, ErrState
	}
	return e, nil
}

func (s *Store) readEnvelope(id string) (Envelope, error) {
	var e Envelope
	if !recordIDPattern.MatchString(id) || privateDir(s.dir) != nil {
		return e, ErrInvalid
	}
	path := filepath.Join(s.dir, id+".json")
	before, err := os.Lstat(path)
	if err != nil {
		return e, err
	}
	if !before.Mode().IsRegular() || before.Mode()&os.ModeSymlink != 0 || before.Size() > 2<<20 {
		return e, ErrState
	}
	open := fileopen.Regular
	if runtime.GOOS == "windows" {
		open = statefs.OpenPrivate
	}
	f, err := open(path)
	if err != nil {
		return e, ErrState
	}
	after, statErr := f.Stat()
	if statErr != nil || !os.SameFile(before, after) || !after.Mode().IsRegular() {
		_ = f.Close()
		return e, ErrState
	}
	d := json.NewDecoder(io.LimitReader(f, (2<<20)+1))
	d.DisallowUnknownFields()
	err = d.Decode(&e)
	var extra any
	extraErr := d.Decode(&extra)
	_ = f.Close()
	created, createdErr := time.Parse(time.RFC3339Nano, e.CreatedAt)
	expires, expiresErr := time.Parse(time.RFC3339Nano, e.ExpiresAt)
	if err != nil || extraErr != io.EOF || e.RecordID != id || !validEnvelopeSource(e) ||
		!digestRefPattern.MatchString(e.TaskRef) || !allowedKind(e.Kind) || createdErr != nil || expiresErr != nil || !created.Before(expires) ||
		!lowerHex(e.PlaintextHash, 32) || e.PlaintextSize < 1 || e.PlaintextSize > MaxPlaintext || e.OmittedCount < 0 || e.OmittedCount > 1024 || e.Algorithm != "aes-256-gcm/v1" {
		return Envelope{}, ErrState
	}
	return e, nil
}

func (s *Store) decryptEnvelope(e Envelope) (payload, error) {
	if err := s.checkCachedKey(); err != nil {
		return payload{}, err
	}
	nonce, nerr := base64.StdEncoding.Strict().DecodeString(e.Nonce)
	ciphertext, cerr := base64.StdEncoding.Strict().DecodeString(e.Ciphertext)
	block, berr := aes.NewCipher(s.key)
	if nerr != nil || cerr != nil || berr != nil || len(nonce) != 12 || len(ciphertext) < 16 {
		return payload{}, ErrState
	}
	gcm, _ := cipher.NewGCM(block)
	plain, err := gcm.Open(nil, nonce, ciphertext, aad(e))
	if err != nil || len(plain) != e.PlaintextSize {
		return payload{}, ErrState
	}
	sum := sha256.Sum256(plain)
	if hex.EncodeToString(sum[:]) != e.PlaintextHash {
		return payload{}, ErrState
	}
	var p payload
	if json.Unmarshal(plain, &p) != nil || p.Schema != "local-raw-task-content/v1" || p.Kind != e.Kind || p.OmittedCount != e.OmittedCount || len(p.Fields) == 0 || len(p.Fields) > 1024 {
		return payload{}, ErrState
	}
	seen := map[string]bool{}
	for _, field := range p.Fields {
		if !pathPattern.MatchString(field.Path) || seen[field.Path] || !safeText(field.Value, MaxPlaintext) || sensitivePath(field.Path) || secretValue.MatchString(field.Value) {
			return payload{}, ErrState
		}
		seen[field.Path] = true
	}
	return p, nil
}

func (s *Store) Read(taskID, id string, now time.Time) ([]Field, Envelope, error) {
	return s.readForSource(taskID, id, now, nil)
}

func (s *Store) readForSource(taskID, id string, now time.Time, source *RuntimeSource) ([]Field, Envelope, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	ref, ok := taskRef(taskID)
	if !ok || now.IsZero() {
		return nil, Envelope{}, ErrInvalid
	}
	e, err := s.readEnvelope(id)
	if err != nil {
		return nil, Envelope{}, err
	}
	if e.TaskRef != ref {
		if source != nil {
			return nil, Envelope{}, ErrDenied
		}
		return nil, Envelope{}, ErrState
	}
	if source != nil && (e.Kind != "output" || e.Source == nil || *e.Source != *source) {
		return nil, Envelope{}, ErrDenied
	}
	expires, err := time.Parse(time.RFC3339Nano, e.ExpiresAt)
	p, err := s.decryptEnvelope(e)
	if err != nil {
		return nil, Envelope{}, ErrState
	}
	if !now.Before(expires) {
		return nil, e, ErrExpired
	}
	out := make([]Field, 0, len(p.Fields))
	for _, field := range p.Fields {
		out = append(out, Field{Path: field.Path, Value: field.Value})
	}
	return out, e, nil
}

type Metadata struct {
	SchemaVersion string `json:"schema_version"`
	Status        string `json:"status"`
	RecordID      string `json:"record_id"`
	TaskRef       string `json:"task_ref"`
	Kind          string `json:"kind"`
	CreatedAt     string `json:"created_at"`
	ExpiresAt     string `json:"expires_at"`
	PlaintextHash string `json:"plaintext_sha256"`
	PlaintextSize int    `json:"plaintext_bytes"`
	OmittedCount  int    `json:"omitted_secret_count"`
}

func envelopeMetadata(e Envelope, now time.Time) Metadata {
	status := "active"
	expires, _ := time.Parse(time.RFC3339Nano, e.ExpiresAt)
	if !now.Before(expires) {
		status = "expired"
	}
	return Metadata{
		SchemaVersion: "local-raw-task-content-record/v1", Status: status, RecordID: e.RecordID,
		TaskRef: e.TaskRef, Kind: e.Kind, CreatedAt: e.CreatedAt, ExpiresAt: e.ExpiresAt,
		PlaintextHash: e.PlaintextHash, PlaintextSize: e.PlaintextSize, OmittedCount: e.OmittedCount,
	}
}

// ListMetadata authenticates every bounded envelope before returning records
// for one task. A corrupt unrelated record fails the entire list.
func (s *Store) ListMetadata(taskID string, now time.Time) ([]Metadata, error) {
	return s.listMetadataForSource(taskID, now, nil)
}

func (s *Store) listMetadataForSource(taskID string, now time.Time, source *RuntimeSource) ([]Metadata, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	ref, ok := taskRef(taskID)
	if !ok || now.IsZero() || privateDir(s.dir) != nil {
		return nil, ErrInvalid
	}
	entries, err := statefs.ReadDir(s.dir)
	if err != nil {
		return nil, ErrState
	}
	if len(entries) > maxAuthorityRecords {
		return nil, ErrBudget
	}
	out := []Metadata{}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".pending-content-") {
			continue
		}
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			return nil, ErrState
		}
		id := strings.TrimSuffix(entry.Name(), ".json")
		e, err := s.readEnvelope(id)
		if err != nil {
			return nil, ErrState
		}
		if _, err := s.decryptEnvelope(e); err != nil {
			return nil, err
		}
		if e.TaskRef == ref && (source == nil || (e.Kind == "output" && e.Source != nil && *e.Source == *source)) {
			out = append(out, envelopeMetadata(e, now))
		}
	}
	return out, nil
}

func (s *Store) Delete(taskID, id string) error {
	storeMu.Lock()
	defer storeMu.Unlock()
	ref, ok := taskRef(taskID)
	if !ok {
		return ErrInvalid
	}
	e, err := s.readEnvelope(id)
	if err != nil {
		return err
	}
	if e.TaskRef != ref {
		return ErrState
	}
	if _, err := s.decryptEnvelope(e); err != nil {
		return err
	}
	if err := statefs.Remove(filepath.Join(s.dir, id+".json")); err != nil {
		return ErrState
	}
	return nil
}

type PurgeResult struct {
	Deleted int
	Bytes   int64
}

// PurgeExpired validates every envelope before removing any. It never touches
// another state directory and leaves audit/evidence stores outside s.dir alone.
func (s *Store) PurgeExpired(now time.Time) (PurgeResult, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	if now.IsZero() || privateDir(s.dir) != nil {
		return PurgeResult{}, ErrInvalid
	}
	entries, err := statefs.ReadDir(s.dir)
	if err != nil {
		return PurgeResult{}, ErrState
	}
	type expiredFile struct {
		id   string
		size int64
	}
	expired := []expiredFile{}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".pending-") {
			continue
		}
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			return PurgeResult{}, ErrState
		}
		id := strings.TrimSuffix(entry.Name(), ".json")
		e, err := s.readEnvelope(id)
		if err != nil {
			return PurgeResult{}, ErrState
		}
		if _, err := s.decryptEnvelope(e); err != nil {
			return PurgeResult{}, err
		}
		expires, err := time.Parse(time.RFC3339Nano, e.ExpiresAt)
		if err != nil {
			return PurgeResult{}, ErrState
		}
		if !now.Before(expires) {
			info, err := entry.Info()
			if err != nil {
				return PurgeResult{}, ErrState
			}
			expired = append(expired, expiredFile{id: id, size: info.Size()})
		}
	}
	result := PurgeResult{}
	for _, item := range expired {
		if err := statefs.Remove(filepath.Join(s.dir, item.id+".json")); err != nil {
			return result, ErrState
		}
		result.Deleted++
		result.Bytes += item.size
	}
	return result, nil
}

// KeyFingerprint is safe status metadata; it does not expose encryption key bytes.
func (s *Store) KeyFingerprint() string {
	sum := sha256.Sum256(s.key)
	return hex.EncodeToString(sum[:])
}
