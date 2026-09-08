package effectevidence

import (
	"bytes"
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
	"siq-agent-security/apps/agentshield/internal/signing"
)

const MaxRecords = 8192

var storeMu sync.RWMutex
var (
	ErrConflict = errors.New("effect_evidence_conflict")
	ErrCapacity = errors.New("effect_evidence_capacity")
	ErrState    = errors.New("effect_evidence_state_unavailable")
	ErrNotFound = errors.New("effect_evidence_not_found")
)

// Record binds the incident projection to its evidence in one immutable file.
type Record struct {
	SchemaVersion string   `json:"schema_version"`
	Evidence      Evidence `json:"evidence"`
	FindingCode   string   `json:"finding_code"`
	RequestDigest string   `json:"request_digest"`
	TaskID        string   `json:"task_id"`
	SigningSchema string   `json:"signing_schema"`
	Signature     string   `json:"signature"`
}

func (r Record) unsigned() map[string]any {
	raw, _ := json.Marshal(r)
	var doc map[string]any
	_ = json.Unmarshal(raw, &doc)
	delete(doc, "signature")
	return doc
}

type Store struct {
	dir string
	key *signing.Key
}

func NewStore(stateDir string, key *signing.Key) (*Store, error) {
	if stateDir == "" || key == nil {
		return nil, ErrState
	}
	s := &Store{dir: filepath.Join(stateDir, "effect-evidence"), key: key}
	if err := os.MkdirAll(s.dir, 0700); err != nil {
		return nil, ErrState
	}
	if err := s.checkDir(); err != nil {
		return nil, err
	}
	return s, nil
}
func (s *Store) checkDir() error {
	info, err := os.Lstat(s.dir)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return ErrState
	}
	return nil
}
func (s *Store) get(id string, now time.Time) (Record, error) {
	var r Record
	if !idPattern.MatchString(id) {
		return r, ErrInvalid
	}
	if err := s.checkDir(); err != nil {
		return r, err
	}
	path := filepath.Join(s.dir, id+".json")
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return r, ErrNotFound
	}
	if err != nil || !info.Mode().IsRegular() || info.Size() > 64<<10 {
		return r, ErrState
	}
	f, err := os.Open(path)
	if err != nil {
		return r, ErrState
	}
	defer f.Close()
	d := json.NewDecoder(io.LimitReader(f, (64<<10)+1))
	d.DisallowUnknownFields()
	if d.Decode(&r) != nil {
		return Record{}, ErrState
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return Record{}, ErrState
	}
	if r.SchemaVersion != "effect-evidence-record/v1" || r.Evidence.EvidenceID != id || r.Evidence.Verify(s.key.Public(), now) != nil || !digestPattern.MatchString(r.RequestDigest) || len(r.TaskID) > 256 || !member(r.FindingCode, "", "unauthorized_effect_observed", "effect_scope_mismatch") || r.SigningSchema != signing.SchemaLocalCanonicalV1 || !signing.VerifyCanonical(s.key.Public(), r.unsigned(), r.Signature) {
		return Record{}, ErrState
	}
	return r, nil
}
func (s *Store) Get(id string, now time.Time) (Record, error) {
	storeMu.RLock()
	defer storeMu.RUnlock()
	return s.get(id, now)
}

// ForAction returns verified immutable records in filename order. Corrupt
// records fail the query instead of silently disappearing from completion data.
func (s *Store) ForAction(actionID string, now time.Time) ([]Record, error) {
	storeMu.RLock()
	defer storeMu.RUnlock()
	if actionID == "" || len(actionID) > 256 {
		return nil, ErrInvalid
	}
	if err := s.checkDir(); err != nil {
		return nil, err
	}
	f, err := os.Open(s.dir)
	if err != nil {
		return nil, ErrState
	}
	entries, err := f.ReadDir(MaxRecords + 1)
	_ = f.Close()
	if err != nil && err != io.EOF {
		return nil, ErrState
	}
	if len(entries) > MaxRecords {
		return nil, ErrCapacity
	}
	ids := []string{}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".effect-") {
			continue
		}
		if !strings.HasSuffix(entry.Name(), ".json") {
			return nil, ErrState
		}
		ids = append(ids, strings.TrimSuffix(entry.Name(), ".json"))
	}
	sort.Strings(ids)
	out := []Record{}
	for _, id := range ids {
		r, err := s.get(id, now)
		if err != nil {
			return nil, err
		}
		if r.Evidence.ActionID == actionID {
			out = append(out, r)
		}
	}
	return out, nil
}

// Submit requires an authenticated observer and a verified engine action. These
// arguments are trusted server dependencies, never request-body fields.
func (s *Store) Submit(input Evidence, action Action, observer Source, now time.Time) (Record, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	if input.Signature != "" || len(action.TaskID) > 256 {
		return Record{}, ErrInvalid
	}
	e, code, err := Correlate(input, action, observer, now)
	if err != nil {
		return Record{}, err
	}
	raw, err := canon.Marshal(input.Unsigned())
	if err != nil {
		return Record{}, ErrInvalid
	}
	sum := sha256.Sum256(raw)
	digest := hex.EncodeToString(sum[:])
	old, err := s.get(e.EvidenceID, now)
	if err == nil {
		if old.RequestDigest != digest || old.TaskID != action.TaskID {
			return Record{}, ErrConflict
		}
		return old, nil
	}
	if !errors.Is(err, ErrNotFound) {
		return Record{}, err
	}
	f, err := os.Open(s.dir)
	if err != nil {
		return Record{}, ErrState
	}
	entries, err := f.ReadDir(MaxRecords + 1)
	_ = f.Close()
	if err != nil && err != io.EOF {
		return Record{}, ErrState
	}
	if len(entries) >= MaxRecords {
		return Record{}, ErrCapacity
	}
	e.Signature, err = s.key.SignCanonical(e.Unsigned())
	if err != nil {
		return Record{}, ErrState
	}
	r := Record{SchemaVersion: "effect-evidence-record/v1", Evidence: e, FindingCode: code, RequestDigest: digest, TaskID: action.TaskID, SigningSchema: signing.SchemaLocalCanonicalV1}
	r.Signature, err = s.key.SignCanonical(r.unsigned())
	if err != nil {
		return Record{}, ErrState
	}
	payload, err := json.Marshal(r)
	if err != nil || len(payload) > 64<<10 {
		return Record{}, ErrInvalid
	}
	tmp, err := os.CreateTemp(s.dir, ".effect-*")
	if err != nil {
		return Record{}, ErrState
	}
	name := tmp.Name()
	defer os.Remove(name)
	_, writeErr := io.Copy(tmp, bytes.NewReader(payload))
	syncErr := tmp.Sync()
	closeErr := tmp.Close()
	if writeErr != nil || syncErr != nil || closeErr != nil {
		return Record{}, ErrState
	}
	if err = os.Link(name, filepath.Join(s.dir, e.EvidenceID+".json")); err != nil {
		return Record{}, ErrState
	}
	return r, nil
}
