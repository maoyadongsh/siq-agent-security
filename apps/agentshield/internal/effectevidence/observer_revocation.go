package effectevidence

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
)

type ObserverRevocation struct {
	SchemaVersion string `json:"schema_version"`
	OwnerDigest   string `json:"owner_digest"`
	RevokedAt     string `json:"revoked_at"`
	SigningSchema string `json:"signing_schema"`
	Signature     string `json:"signature"`
}

func (r ObserverRevocation) unsigned() map[string]any {
	return map[string]any{"schema_version": r.SchemaVersion, "owner_digest": r.OwnerDigest, "revoked_at": r.RevokedAt, "signing_schema": r.SigningSchema}
}
func (s *Store) revocationDir() (string, error) {
	dir := filepath.Join(filepath.Dir(s.dir), "effect-observer-revocations")
	if os.MkdirAll(dir, 0700) != nil {
		return "", ErrState
	}
	info, err := os.Lstat(dir)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return "", ErrState
	}
	return dir, nil
}
func (s *Store) getObserverRevocation(owner string) (ObserverRevocation, error) {
	var r ObserverRevocation
	if !digestPattern.MatchString(owner) {
		return r, ErrInvalid
	}
	dir, err := s.revocationDir()
	if err != nil {
		return r, err
	}
	path := filepath.Join(dir, owner+".json")
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return r, ErrNotFound
	}
	if err != nil || !info.Mode().IsRegular() || info.Size() > 4096 {
		return r, ErrState
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return r, ErrState
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(&r) != nil {
		return r, ErrState
	}
	var extra any
	_, te := time.Parse(time.RFC3339Nano, r.RevokedAt)
	if d.Decode(&extra) != io.EOF || te != nil || len(r.RevokedAt) > 64 || r.SchemaVersion != "effect-observer-revocation/v1" || r.OwnerDigest != owner || r.SigningSchema != signing.SchemaLocalCanonicalV1 || !signing.VerifyCanonical(s.key.Public(), r.unsigned(), r.Signature) {
		return ObserverRevocation{}, ErrState
	}
	return r, nil
}
func (s *Store) ObserverRevoked(owner string) (bool, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	_, err := s.getObserverRevocation(owner)
	if errors.Is(err, ErrNotFound) {
		return false, nil
	}
	return err == nil, err
}
func (s *Store) RevokeObserver(owner string, now time.Time) (ObserverRevocation, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	old, err := s.getObserverRevocation(owner)
	if err == nil {
		return old, nil
	}
	if !errors.Is(err, ErrNotFound) {
		return ObserverRevocation{}, err
	}
	dir, err := s.revocationDir()
	if err != nil {
		return ObserverRevocation{}, err
	}
	f, err := os.Open(dir)
	if err != nil {
		return ObserverRevocation{}, ErrState
	}
	entries, err := f.ReadDir(MaxRecords + 1)
	_ = f.Close()
	if err != nil && err != io.EOF {
		return ObserverRevocation{}, ErrState
	}
	if len(entries) >= MaxRecords {
		return ObserverRevocation{}, ErrCapacity
	}
	r := ObserverRevocation{SchemaVersion: "effect-observer-revocation/v1", OwnerDigest: owner, RevokedAt: now.UTC().Format(time.RFC3339Nano), SigningSchema: signing.SchemaLocalCanonicalV1}
	r.Signature, err = s.key.SignCanonical(r.unsigned())
	if err != nil {
		return r, ErrState
	}
	raw, err := json.Marshal(r)
	if err != nil {
		return r, ErrInvalid
	}
	tmp, err := os.CreateTemp(dir, ".revocation-*")
	if err != nil {
		return r, ErrState
	}
	name := tmp.Name()
	defer os.Remove(name)
	_, we := tmp.Write(raw)
	se := tmp.Sync()
	ce := tmp.Close()
	if we != nil || se != nil || ce != nil {
		return ObserverRevocation{}, ErrState
	}
	if os.Link(name, filepath.Join(dir, owner+".json")) != nil {
		return ObserverRevocation{}, ErrState
	}
	return r, nil
}
