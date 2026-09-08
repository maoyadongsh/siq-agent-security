package effectevidence

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/signing"
)

type PendingFile struct {
	SchemaVersion  string           `json:"schema_version"`
	ID             string           `json:"observation_id"`
	ActionID       string           `json:"action_id"`
	ReceiptID      string           `json:"decision_receipt_id"`
	Scope          provenance.Scope `json:"scope"`
	Source         Source           `json:"source"`
	Before         FileSnapshot     `json:"before"`
	OwnerDigest    string           `json:"owner_digest"`
	ExpectedDigest string           `json:"expected_digest"`
	MaxBytes       int64            `json:"max_bytes"`
	ExpiresAt      string           `json:"expires_at"`
	SigningSchema  string           `json:"signing_schema"`
	Signature      string           `json:"signature"`
}

func (p PendingFile) unsigned() map[string]any {
	raw, _ := json.Marshal(p)
	value, _ := canon.Decode(raw)
	m := value.(map[string]any)
	delete(m, "signature")
	return m
}
func (p PendingFile) valid() bool {
	expiry, err := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	captured, e := time.Parse(time.RFC3339Nano, p.Before.CapturedAt)
	if err != nil || e != nil || !expiry.After(captured) || len(p.ExpiresAt) > 64 || !validSnapshot(p.Before) || p.SchemaVersion != "file-observation-pending/v1" || !idPattern.MatchString(p.ID) || !digestPattern.MatchString(p.OwnerDigest) || !digestPattern.MatchString(p.ExpectedDigest) || p.MaxBytes < 1 || p.MaxBytes > MaxFileBytes || p.Before.Size > p.MaxBytes || p.Source.Type != "host_observer" || p.Source.Independence != "host_independent" || p.SigningSchema != signing.SchemaLocalCanonicalV1 {
		return false
	}
	for _, s := range []string{p.ActionID, p.ReceiptID, p.Scope.Platform, p.Scope.SessionID, p.Scope.AgentID, p.Scope.TaskID, p.Source.SourceID} {
		if len(s) == 0 || len(s) > 256 {
			return false
		}
	}
	return true
}
func (s *Store) pendingDir() (string, error) {
	dir := s.dir + "-pending"
	if err := os.MkdirAll(dir, 0700); err != nil {
		return "", ErrState
	}
	info, err := os.Lstat(dir)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return "", ErrState
	}
	return dir, nil
}
func (s *Store) getPending(id string) (PendingFile, error) {
	var p PendingFile
	if !idPattern.MatchString(id) {
		return p, ErrInvalid
	}
	dir, err := s.pendingDir()
	if err != nil {
		return p, err
	}
	path := filepath.Join(dir, id+".json")
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return p, ErrNotFound
	}
	if err != nil || !info.Mode().IsRegular() || info.Size() > 64<<10 {
		return p, ErrState
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return p, ErrState
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(&p) != nil {
		return PendingFile{}, ErrState
	}
	var extra any
	if d.Decode(&extra) != io.EOF || !p.valid() || !signing.VerifyCanonical(s.key.Public(), p.unsigned(), p.Signature) || p.ID != id {
		return PendingFile{}, ErrState
	}
	return p, nil
}
func (s *Store) GetPendingFile(id string) (PendingFile, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	return s.getPending(id)
}
func (s *Store) SavePendingFile(p PendingFile) (PendingFile, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	if !p.valid() || p.Signature != "" {
		return PendingFile{}, ErrInvalid
	}
	old, err := s.getPending(p.ID)
	if err == nil {
		a, _ := canon.Marshal(old.unsigned())
		b, _ := canon.Marshal(p.unsigned())
		if !bytes.Equal(a, b) {
			return PendingFile{}, ErrConflict
		}
		return old, nil
	}
	if !errors.Is(err, ErrNotFound) {
		return PendingFile{}, err
	}
	dir, err := s.pendingDir()
	if err != nil {
		return PendingFile{}, err
	}
	f, err := os.Open(dir)
	if err != nil {
		return PendingFile{}, ErrState
	}
	entries, err := f.ReadDir(MaxRecords + 1)
	_ = f.Close()
	if err != nil && err != io.EOF {
		return PendingFile{}, ErrState
	}
	if len(entries) >= MaxRecords {
		return PendingFile{}, ErrCapacity
	}
	p.Signature, err = s.key.SignCanonical(p.unsigned())
	if err != nil {
		return PendingFile{}, ErrState
	}
	raw, err := json.Marshal(p)
	if err != nil || len(raw) > 64<<10 {
		return PendingFile{}, ErrInvalid
	}
	tmp, err := os.CreateTemp(dir, ".pending-*")
	if err != nil {
		return PendingFile{}, ErrState
	}
	name := tmp.Name()
	defer os.Remove(name)
	_, we := tmp.Write(raw)
	se := tmp.Sync()
	ce := tmp.Close()
	if we != nil || se != nil || ce != nil {
		return PendingFile{}, ErrState
	}
	if os.Link(name, filepath.Join(dir, p.ID+".json")) != nil {
		return PendingFile{}, ErrState
	}
	return p, nil
}
