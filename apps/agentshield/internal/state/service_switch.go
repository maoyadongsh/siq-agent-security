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
	"runtime"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

const serviceSwitchPending = "service-switch.pending.json"

type ServiceSwitch struct {
	SchemaVersion string            `json:"schema_version"`
	SourceRecord  UserServiceRecord `json:"source_record"`
	TargetRecord  UserServiceRecord `json:"target_record"`
	SourceUnit    string            `json:"source_unit"`
	TargetUnit    string            `json:"target_unit"`
	Signature     string            `json:"signature"`
}

func (p ServiceSwitch) unsigned() (map[string]any, error) {
	raw, err := json.Marshal(p)
	if err != nil {
		return nil, err
	}
	v, err := canon.Decode(raw)
	if err != nil {
		return nil, err
	}
	doc := v.(map[string]any)
	delete(doc, "signature")
	return doc, nil
}
func (s *Store) serviceWriter(w *Writer) error {
	if w == nil || filepath.Clean(w.Dir) != filepath.Clean(s.Dir) {
		return ErrWriterBusy
	}
	pid, owner, err := readLockFile(w.path)
	if err != nil || pid != os.Getpid() || pid != w.pid || owner != w.owner {
		return ErrWriterBusy
	}
	return nil
}
func (s *Store) CheckServiceSwitchPending() error {
	if _, err := os.Lstat(filepath.Join(s.Dir, serviceSwitchPending)); errors.Is(err, os.ErrNotExist) {
		return nil
	}
	return errors.New("state: service configuration switch pending; recover it before starting")
}
func (s *Store) PrepareServiceSwitch(w *Writer, key *signing.Key, source, target []byte) (string, error) {
	if err := s.serviceWriter(w); err != nil {
		return "", err
	}
	if err := s.CheckServiceSwitchPending(); err != nil {
		return "", err
	}
	before, err := s.VerifyUserService(key, source)
	if err != nil {
		return "", err
	}
	after, err := s.expectedUserService(key, target)
	if err != nil {
		return "", err
	}
	if bytes.Equal(source, target) {
		return "", errors.New("state: service switch has no change")
	}
	after.Signature, err = key.SignCanonical(after.unsigned())
	if err != nil {
		return "", err
	}
	plan := ServiceSwitch{SchemaVersion: "local-service-switch/v1", SourceRecord: before, TargetRecord: after, SourceUnit: string(source), TargetUnit: string(target)}
	doc, err := plan.unsigned()
	if err != nil {
		return "", err
	}
	plan.Signature, err = key.SignCanonical(doc)
	if err != nil {
		return "", err
	}
	raw, err := json.Marshal(plan)
	if err != nil {
		return "", err
	}
	hash := sha256.Sum256(raw)
	id := hex.EncodeToString(hash[:])
	if err = publishCommitFile(filepath.Join(s.Dir, "service-switches", id+".json"), raw); err != nil {
		return "", err
	}
	if err = publishCommitFile(filepath.Join(s.Dir, serviceSwitchPending), raw); err != nil {
		return "", err
	}
	return id, nil
}
func (s *Store) validateServiceSwitch(key *signing.Key, raw []byte) (ServiceSwitch, error) {
	var p ServiceSwitch
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if key == nil || dec.Decode(&p) != nil || dec.Decode(new(any)) != io.EOF || p.SchemaVersion != "local-service-switch/v1" {
		return p, errors.New("state: invalid service switch")
	}
	doc, err := p.unsigned()
	if err != nil || !signing.VerifyCanonical(key.Public(), doc, p.Signature) {
		return p, errors.New("state: invalid service switch signature")
	}
	for _, pair := range []struct {
		record UserServiceRecord
		unit   string
	}{{p.SourceRecord, p.SourceUnit}, {p.TargetRecord, p.TargetUnit}} {
		expected, err := s.expectedUserService(key, []byte(pair.unit))
		if err != nil {
			return p, err
		}
		recordRaw, err := json.Marshal(pair.record)
		if err != nil {
			return p, err
		}
		if _, err = verifyServiceRecord(recordRaw, key, expected); err != nil {
			return p, err
		}
	}
	if p.SourceUnit == p.TargetUnit {
		return p, errors.New("state: empty service switch")
	}
	return p, nil
}

// ApplyServiceSwitch only changes the two owned configuration files. Caller
// must keep the manager stopped; reload/readiness are a separate phase.
func (s *Store) ApplyServiceSwitch(w *Writer, key *signing.Key, id string) error {
	if err := s.serviceWriter(w); err != nil {
		return err
	}
	decoded, err := hex.DecodeString(id)
	if err != nil || len(decoded) != 32 || hex.EncodeToString(decoded) != id {
		return errors.New("state: invalid service switch id")
	}
	raw, err := readInitializationFile(filepath.Join(s.Dir, "service-switches", id+".json"))
	if err != nil {
		return err
	}
	hash := sha256.Sum256(raw)
	if hex.EncodeToString(hash[:]) != id {
		return errors.New("state: service switch identity mismatch")
	}
	p, err := s.validateServiceSwitch(key, raw)
	if err != nil {
		return err
	}
	pending, err := readInitializationFile(filepath.Join(s.Dir, serviceSwitchPending))
	if errors.Is(err, os.ErrNotExist) {
		done, doneErr := readInitializationFile(filepath.Join(s.Dir, "service-switches", id+".done.json"))
		if doneErr != nil || !bytes.Equal(done, raw) {
			return errors.New("state: service switch not pending or completed")
		}
	} else if err != nil || !bytes.Equal(pending, raw) {
		return errors.New("state: another or invalid service switch pending")
	}
	before, _ := json.Marshal(p.SourceRecord)
	after, _ := json.Marshal(p.TargetRecord)
	images := []struct {
		path          string
		before, after []byte
	}{
		{filepath.Join(s.Dir, p.SourceRecord.UnitName), []byte(p.SourceUnit), []byte(p.TargetUnit)},
		{filepath.Join(s.Dir, "user-service.json"), before, after},
	}
	// Validate both before replacing either. Recovery accepts a partially applied
	// pair but never treats unrelated bytes as an old version.
	for _, image := range images {
		current, err := readInitializationFile(image.path)
		if err != nil {
			return err
		}
		if (pending == nil && !bytes.Equal(current, image.after)) || (!bytes.Equal(current, image.before) && !bytes.Equal(current, image.after)) {
			return errors.New("state: service switch input drift")
		}
	}
	for _, image := range images {
		if err = replaceServiceImage(image.path, image.before, image.after); err != nil {
			return err
		}
	}
	if err = publishCommitFile(filepath.Join(s.Dir, "service-switches", id+".done.json"), raw); err != nil {
		return err
	}
	if err == nil && pending != nil {
		current, err := readInitializationFile(filepath.Join(s.Dir, serviceSwitchPending))
		if err != nil || !bytes.Equal(current, raw) {
			return errors.New("state: pending switch changed")
		}
		if err = os.Remove(filepath.Join(s.Dir, serviceSwitchPending)); err != nil {
			return err
		}
		return syncServiceDirectory(s.Dir)
	}
	return nil
}
func replaceServiceImage(path string, before, after []byte) error {
	current, err := readInitializationFile(path)
	if err != nil {
		return err
	}
	if bytes.Equal(current, after) {
		return nil
	}
	if !bytes.Equal(current, before) {
		return errors.New("state: service switch image drift")
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".service-switch-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	defer f.Close()
	if _, err = f.Write(after); err != nil {
		return err
	}
	if err = f.Sync(); err != nil {
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	if err = os.Rename(f.Name(), path); err != nil {
		return err
	}
	return syncServiceDirectory(filepath.Dir(path))
}
func syncServiceDirectory(path string) error {
	if runtime.GOOS == "windows" {
		return nil
	}
	d, err := os.Open(path)
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}
