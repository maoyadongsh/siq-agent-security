package state

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
)

type UserServiceRecord struct {
	SchemaVersion string `json:"schema_version"`
	InstanceID    string `json:"instance_id"`
	DirectoryID   string `json:"state_directory_id"`
	UnitName      string `json:"unit_name"`
	UnitSHA256    string `json:"unit_sha256"`
	Signature     string `json:"signature"`
}

func (r UserServiceRecord) unsigned() map[string]any {
	return map[string]any{"schema_version": r.SchemaVersion, "instance_id": r.InstanceID, "state_directory_id": r.DirectoryID, "unit_name": r.UnitName, "unit_sha256": r.UnitSHA256}
}
func (s *Store) expectedUserService(key *signing.Key, unit []byte) (UserServiceRecord, error) {
	var r UserServiceRecord
	if key == nil || len(unit) == 0 || len(unit) > 16384 {
		return r, errors.New("state: invalid service configuration")
	}
	instance, err := s.ReadLocalInstance()
	if err != nil {
		return r, err
	}
	directory, err := s.DirectoryID()
	if err != nil {
		return r, err
	}
	hash := sha256.Sum256(unit)
	return UserServiceRecord{SchemaVersion: "local-user-service-record/v1", InstanceID: instance.InstanceID, DirectoryID: directory, UnitName: "siq-agent-security-" + instance.InstanceID[:32] + ".service", UnitSHA256: hex.EncodeToString(hash[:])}, nil
}
func verifyServiceRecord(raw []byte, key *signing.Key, expected UserServiceRecord) (UserServiceRecord, error) {
	var saved UserServiceRecord
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if dec.Decode(&saved) != nil || dec.Decode(new(any)) != io.EOF || !signing.VerifyCanonical(key.Public(), saved.unsigned(), saved.Signature) {
		return UserServiceRecord{}, errors.New("state: invalid service ownership record")
	}
	expected.Signature = saved.Signature
	if expected != saved {
		return UserServiceRecord{}, errors.New("state: service configuration changed; explicit migration required")
	}
	return saved, nil
}

// PrepareUserService publishes signed intent before exclusive unit publication.
func (s *Store) PrepareUserService(w *Writer, key *signing.Key, unit []byte) (UserServiceRecord, error) {
	var empty UserServiceRecord
	if w == nil || filepath.Clean(w.Dir) != filepath.Clean(s.Dir) {
		return empty, ErrWriterBusy
	}
	pid, owner, err := readLockFile(w.path)
	if err != nil || pid != os.Getpid() || pid != w.pid || owner != w.owner {
		return empty, ErrWriterBusy
	}
	record, err := s.expectedUserService(key, unit)
	if err != nil {
		return empty, err
	}
	recordPath := filepath.Join(s.Dir, "user-service.json")
	unitPath := filepath.Join(s.Dir, record.UnitName)
	raw, err := readInitializationFile(recordPath)
	if errors.Is(err, os.ErrNotExist) {
		if _, err := os.Lstat(unitPath); !errors.Is(err, os.ErrNotExist) {
			return empty, errors.New("state: unowned service file exists")
		}
		record.Signature, err = key.SignCanonical(record.unsigned())
		if err != nil {
			return empty, err
		}
		raw, err = json.Marshal(record)
		if err != nil {
			return empty, err
		}
		if err = publishCommitFile(recordPath, raw); err != nil {
			return empty, err
		}
	} else if err != nil {
		return empty, err
	} else {
		record, err = verifyServiceRecord(raw, key, record)
		if err != nil {
			return empty, err
		}
	}
	existing, err := readInitializationFile(unitPath)
	if errors.Is(err, os.ErrNotExist) {
		err = publishCommitFile(unitPath, unit)
	} else if err == nil && !bytes.Equal(existing, unit) {
		err = errors.New("state: service unit changed; restore before retrying")
	}
	if err != nil {
		return empty, err
	}
	return record, nil
}

// VerifyUserService never writes, repairs or acquires the daemon's writer.
func (s *Store) VerifyUserService(key *signing.Key, unit []byte) (UserServiceRecord, error) {
	r, err := s.expectedUserService(key, unit)
	if err != nil {
		return UserServiceRecord{}, err
	}
	raw, err := readInitializationFile(filepath.Join(s.Dir, "user-service.json"))
	if err != nil {
		return UserServiceRecord{}, err
	}
	r, err = verifyServiceRecord(raw, key, r)
	if err != nil {
		return UserServiceRecord{}, err
	}
	actual, err := readInitializationFile(filepath.Join(s.Dir, r.UnitName))
	if err != nil {
		return UserServiceRecord{}, err
	}
	if !bytes.Equal(actual, unit) {
		return UserServiceRecord{}, errors.New("state: service configuration drift")
	}
	return r, nil
}
