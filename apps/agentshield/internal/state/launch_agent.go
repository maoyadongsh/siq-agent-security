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

type LaunchAgentRecord struct {
	SchemaVersion string `json:"schema_version"`
	InstanceID    string `json:"instance_id"`
	DirectoryID   string `json:"state_directory_id"`
	Label         string `json:"label"`
	PlistSHA256   string `json:"plist_sha256"`
	Signature     string `json:"signature"`
}

func (r LaunchAgentRecord) unsigned() map[string]any {
	return map[string]any{"schema_version": r.SchemaVersion, "instance_id": r.InstanceID, "state_directory_id": r.DirectoryID, "label": r.Label, "plist_sha256": r.PlistSHA256}
}
func (s *Store) expectedLaunchAgent(key *signing.Key, unit []byte) (LaunchAgentRecord, error) {
	var r LaunchAgentRecord
	if key == nil || len(unit) == 0 || len(unit) > 16384 {
		return r, errors.New("state: invalid LaunchAgent configuration")
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
	return LaunchAgentRecord{SchemaVersion: "local-launch-agent-record/v1", InstanceID: instance.InstanceID, DirectoryID: directory, Label: "dev.siq.agent-security." + instance.InstanceID, PlistSHA256: hex.EncodeToString(hash[:])}, nil
}
func verifyLaunchAgentRecord(raw []byte, key *signing.Key, expected LaunchAgentRecord) (LaunchAgentRecord, error) {
	var saved LaunchAgentRecord
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if dec.Decode(&saved) != nil || dec.Decode(new(any)) != io.EOF || !signing.VerifyCanonical(key.Public(), saved.unsigned(), saved.Signature) {
		return LaunchAgentRecord{}, errors.New("state: invalid LaunchAgent ownership record")
	}
	expected.Signature = saved.Signature
	if expected != saved {
		return LaunchAgentRecord{}, errors.New("state: LaunchAgent configuration changed; explicit migration required")
	}
	return saved, nil
}

// PrepareLaunchAgent publishes signed intent before exclusive unit publication.
func (s *Store) PrepareLaunchAgent(w *Writer, key *signing.Key, unit []byte) (LaunchAgentRecord, error) {
	var empty LaunchAgentRecord
	if err := s.serviceWriter(w); err != nil {
		return empty, err
	}
	record, err := s.expectedLaunchAgent(key, unit)
	if err != nil {
		return empty, err
	}
	recordPath := filepath.Join(s.Dir, "launch-agent.json")
	unitPath := filepath.Join(s.Dir, record.Label+".plist")
	raw, err := readInitializationFile(recordPath)
	if errors.Is(err, os.ErrNotExist) {
		if _, err := os.Lstat(unitPath); !errors.Is(err, os.ErrNotExist) {
			return empty, errors.New("state: unowned LaunchAgent file exists")
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
		record, err = verifyLaunchAgentRecord(raw, key, record)
		if err != nil {
			return empty, err
		}
	}
	existing, err := readInitializationFile(unitPath)
	if errors.Is(err, os.ErrNotExist) {
		err = publishCommitFile(unitPath, unit)
	} else if err == nil && !bytes.Equal(existing, unit) {
		err = errors.New("state: LaunchAgent plist changed; restore before retrying")
	}
	if err != nil {
		return empty, err
	}
	return record, nil
}

// VerifyLaunchAgent never writes, repairs or acquires the daemon's writer.
func (s *Store) VerifyLaunchAgent(key *signing.Key, unit []byte) (LaunchAgentRecord, error) {
	r, err := s.expectedLaunchAgent(key, unit)
	if err != nil {
		return LaunchAgentRecord{}, err
	}
	raw, err := readInitializationFile(filepath.Join(s.Dir, "launch-agent.json"))
	if err != nil {
		return LaunchAgentRecord{}, err
	}
	r, err = verifyLaunchAgentRecord(raw, key, r)
	if err != nil {
		return LaunchAgentRecord{}, err
	}
	actual, err := readInitializationFile(filepath.Join(s.Dir, r.Label+".plist"))
	if err != nil {
		return LaunchAgentRecord{}, err
	}
	if !bytes.Equal(actual, unit) {
		return LaunchAgentRecord{}, errors.New("state: LaunchAgent configuration drift")
	}
	return r, nil
}
