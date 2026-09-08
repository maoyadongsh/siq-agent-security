package provenance

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"sync"
	"time"
)

var storeMu sync.RWMutex

const maxRecordBytes = 64 << 10
const maxIssuers = 4096

type Store struct {
	dir string
	key *signing.Key
}
type issuerRecord struct {
	SchemaVersion string `json:"schema_version"`
	Issuer        Issuer `json:"issuer"`
	SigningSchema string `json:"signing_schema"`
	Signature     string `json:"signature"`
}
type issuerRevocation struct {
	SchemaVersion string `json:"schema_version"`
	IssuerID      string `json:"issuer_id"`
	IssuerDigest  string `json:"issuer_digest"`
	RevokedAt     string `json:"revoked_at"`
	SigningSchema string `json:"signing_schema"`
	Signature     string `json:"signature"`
}

func Open(dir string, key *signing.Key) (*Store, error) {
	if dir == "" || key == nil {
		return nil, failure("provenance_state_unavailable")
	}
	for _, name := range []string{"provenance-issuers", "provenance-issuer-revocations"} {
		p := filepath.Join(dir, name)
		if err := os.MkdirAll(p, 0700); err != nil {
			return nil, err
		}
		fi, err := os.Lstat(p)
		if err != nil || !fi.IsDir() || fi.Mode()&os.ModeSymlink != 0 {
			return nil, failure("provenance_state_unavailable")
		}
	}
	return &Store{dir: dir, key: key}, nil
}
func unsignedRecord(value any) map[string]any {
	raw, _ := json.Marshal(value)
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	delete(m, "signature")
	return m
}
func (s *Store) recordPath(kind, id string) string { return filepath.Join(s.dir, kind, id+".json") }
func publishRecord(path string, value any) error {
	raw, err := json.Marshal(value)
	if err != nil || len(raw) > maxRecordBytes {
		return failure("provenance_record_invalid")
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".provenance-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(raw); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Link(f.Name(), path)
}
func readRecord(path string, out any) error {
	fi, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !fi.Mode().IsRegular() || fi.Size() > maxRecordBytes {
		return failure("provenance_record_invalid")
	}
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	dec := json.NewDecoder(io.LimitReader(f, maxRecordBytes+1))
	dec.DisallowUnknownFields()
	dec.UseNumber()
	if err := dec.Decode(out); err != nil {
		return failure("provenance_record_invalid")
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		return failure("provenance_record_invalid")
	}
	return nil
}
func (s *Store) loadIssuer(id string) (issuerRecord, error) {
	var r issuerRecord
	if !identifier.MatchString(id) {
		return r, failure("provenance_issuer_untrusted")
	}
	if err := readRecord(s.recordPath("provenance-issuers", id), &r); err != nil {
		return r, failure("provenance_issuer_untrusted")
	}
	if r.SchemaVersion != "provenance-issuer-record/v1" || r.Issuer.IssuerID != id || r.Issuer.Validate() != nil || r.SigningSchema != signing.SchemaLocalCanonicalV1 || signing.VerifyWithSchema(r.SigningSchema, s.key.Public(), unsignedRecord(r), r.Signature) != nil {
		return r, failure("provenance_issuer_untrusted")
	}
	return r, nil
}
func (s *Store) RegisterIssuer(i Issuer) (Issuer, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	if err := i.Validate(); err != nil {
		return Issuer{}, err
	}
	if i.RevokedAt != "" {
		return Issuer{}, failure("provenance_issuer_untrusted")
	}
	path := s.recordPath("provenance-issuers", i.IssuerID)
	if _, err := os.Lstat(path); err == nil {
		old, err := s.getIssuer(i.IssuerID)
		if err != nil {
			return Issuer{}, err
		}
		a, _ := json.Marshal(old)
		b, _ := json.Marshal(i)
		if bytes.Equal(a, b) {
			return old, nil
		}
		return Issuer{}, failure("provenance_issuer_conflict")
	} else if !errors.Is(err, os.ErrNotExist) {
		return Issuer{}, failure("provenance_state_unavailable")
	}
	f, err := os.Open(filepath.Join(s.dir, "provenance-issuers"))
	if err != nil {
		return Issuer{}, err
	}
	entries, err := f.ReadDir(maxIssuers + 1)
	_ = f.Close()
	if err != nil && err != io.EOF {
		return Issuer{}, err
	}
	if len(entries) >= maxIssuers {
		return Issuer{}, failure("provenance_capacity")
	}
	r := issuerRecord{SchemaVersion: "provenance-issuer-record/v1", Issuer: i, SigningSchema: signing.SchemaLocalCanonicalV1}
	r.Signature, err = s.key.SignCanonical(unsignedRecord(r))
	if err != nil {
		return Issuer{}, err
	}
	if err := publishRecord(path, r); err != nil {
		return Issuer{}, err
	}
	return i, nil
}
func (s *Store) getIssuer(id string) (Issuer, error) {
	r, err := s.loadIssuer(id)
	if err != nil {
		return Issuer{}, err
	}
	var revoked issuerRevocation
	err = readRecord(s.recordPath("provenance-issuer-revocations", id), &revoked)
	if errors.Is(err, os.ErrNotExist) {
		return r.Issuer, nil
	}
	if err != nil {
		return Issuer{}, failure("provenance_issuer_untrusted")
	}
	digest, _ := ContentDigest(unsignedRecord(r))
	_, dateErr := time.Parse(time.RFC3339, revoked.RevokedAt)
	if revoked.SchemaVersion != "provenance-issuer-revocation/v1" || revoked.IssuerID != id || revoked.IssuerDigest != digest || dateErr != nil || revoked.SigningSchema != signing.SchemaLocalCanonicalV1 || signing.VerifyWithSchema(revoked.SigningSchema, s.key.Public(), unsignedRecord(revoked), revoked.Signature) != nil {
		return Issuer{}, failure("provenance_issuer_untrusted")
	}
	r.Issuer.RevokedAt = revoked.RevokedAt
	return r.Issuer, nil
}
func (s *Store) GetIssuer(id string) (Issuer, error) {
	storeMu.RLock()
	defer storeMu.RUnlock()
	return s.getIssuer(id)
}
func (s *Store) RevokeIssuer(id string, now time.Time) (Issuer, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	i, err := s.getIssuer(id)
	if err != nil {
		return Issuer{}, err
	}
	if i.RevokedAt != "" {
		return i, nil
	}
	r, err := s.loadIssuer(id)
	if err != nil {
		return Issuer{}, err
	}
	digest, _ := ContentDigest(unsignedRecord(r))
	v := issuerRevocation{SchemaVersion: "provenance-issuer-revocation/v1", IssuerID: id, IssuerDigest: digest, RevokedAt: now.UTC().Format(time.RFC3339), SigningSchema: signing.SchemaLocalCanonicalV1}
	v.Signature, err = s.key.SignCanonical(unsignedRecord(v))
	if err != nil {
		return Issuer{}, err
	}
	if err := publishRecord(s.recordPath("provenance-issuer-revocations", id), v); err != nil {
		return Issuer{}, err
	}
	i.RevokedAt = v.RevokedAt
	return i, nil
}
