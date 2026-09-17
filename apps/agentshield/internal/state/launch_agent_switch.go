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
	"siq-agent-security/apps/agentshield/internal/statefs"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

const launchAgentSwitchSchema = "local-launch-agent-switch/v1"

// LaunchAgentSwitch is the macOS counterpart of ServiceSwitch. It shares the
// journal directory and pending gate but never validates as a Linux journal.
type LaunchAgentSwitch struct {
	BinaryBindings ServiceBinaryBindings `json:"binary_bindings"`
	SchemaVersion  string                `json:"schema_version"`
	SourceRecord   LaunchAgentRecord     `json:"source_record"`
	TargetRecord   LaunchAgentRecord     `json:"target_record"`
	SourcePlist    string                `json:"source_plist"`
	TargetPlist    string                `json:"target_plist"`
	Signature      string                `json:"signature"`
}

func (p LaunchAgentSwitch) unsigned() (map[string]any, error) {
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

// PrepareLaunchAgentSwitch journals a caller-verified plist pair with binary
// digests. It does not touch launchd or establish release authenticity.
func (s *Store) PrepareLaunchAgentSwitch(w *Writer, key *signing.Key, source, target []byte, bindings ServiceBinaryBindings) (string, error) {
	if !bindings.valid() {
		return "", errors.New("state: invalid service binary bindings")
	}
	if err := s.serviceWriter(w); err != nil {
		return "", err
	}
	if err := s.CheckServiceSwitchPending(); err != nil {
		return "", err
	}
	before, err := s.VerifyLaunchAgent(key, source)
	if err != nil {
		return "", err
	}
	after, err := s.expectedLaunchAgent(key, target)
	if err != nil {
		return "", err
	}
	if bytes.Equal(source, target) {
		return "", errors.New("state: LaunchAgent switch has no change")
	}
	after.Signature, err = key.SignCanonical(after.unsigned())
	if err != nil {
		return "", err
	}
	plan := LaunchAgentSwitch{BinaryBindings: bindings, SchemaVersion: launchAgentSwitchSchema, SourceRecord: before, TargetRecord: after, SourcePlist: string(source), TargetPlist: string(target)}
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

func (s *Store) validateLaunchAgentSwitch(key *signing.Key, raw []byte) (LaunchAgentSwitch, error) {
	var p LaunchAgentSwitch
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if key == nil || dec.Decode(&p) != nil || dec.Decode(new(any)) != io.EOF {
		return p, errors.New("state: invalid LaunchAgent switch")
	}
	if p.SchemaVersion != launchAgentSwitchSchema || !p.BinaryBindings.valid() {
		return p, errors.New("state: invalid LaunchAgent switch schema or binary bindings")
	}
	doc, err := p.unsigned()
	if err != nil || !signing.VerifyCanonical(key.Public(), doc, p.Signature) {
		return p, errors.New("state: invalid LaunchAgent switch signature")
	}
	for _, pair := range []struct {
		record LaunchAgentRecord
		unit   string
	}{{p.SourceRecord, p.SourcePlist}, {p.TargetRecord, p.TargetPlist}} {
		expected, err := s.expectedLaunchAgent(key, []byte(pair.unit))
		if err != nil {
			return p, err
		}
		recordRaw, err := json.Marshal(pair.record)
		if err != nil {
			return p, err
		}
		if _, err = verifyLaunchAgentRecord(recordRaw, key, expected); err != nil {
			return p, err
		}
	}
	if p.SourcePlist == p.TargetPlist || p.SourceRecord.Label != p.TargetRecord.Label {
		return p, errors.New("state: empty or relabelled LaunchAgent switch")
	}
	return p, nil
}

// ApplyLaunchAgentSwitch replaces only the owned plist and ownership record.
// The caller keeps the job stopped; bootout/bootstrap are a separate phase.
func (s *Store) ApplyLaunchAgentSwitch(w *Writer, key *signing.Key, id string) error {
	if err := s.serviceWriter(w); err != nil {
		return err
	}
	raw, p, err := s.readLaunchAgentSwitch(key, id)
	if err != nil {
		return err
	}
	pending, err := readInitializationFile(filepath.Join(s.Dir, serviceSwitchPending))
	if errors.Is(err, os.ErrNotExist) {
		done, doneErr := readInitializationFile(filepath.Join(s.Dir, "service-switches", id+".done.json"))
		if doneErr != nil || !bytes.Equal(done, raw) {
			return errors.New("state: LaunchAgent switch not pending or completed")
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
		{filepath.Join(s.Dir, p.SourceRecord.Label+".plist"), []byte(p.SourcePlist), []byte(p.TargetPlist)},
		{filepath.Join(s.Dir, "launch-agent.json"), before, after},
	}
	for _, image := range images {
		current, err := readInitializationFile(image.path)
		if err != nil {
			return err
		}
		if (pending == nil && !bytes.Equal(current, image.after)) || (!bytes.Equal(current, image.before) && !bytes.Equal(current, image.after)) {
			return errors.New("state: LaunchAgent switch input drift")
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
	if pending != nil {
		current, err := readInitializationFile(filepath.Join(s.Dir, serviceSwitchPending))
		if err != nil || !bytes.Equal(current, raw) {
			return errors.New("state: pending switch changed")
		}
		if err = statefs.Remove(filepath.Join(s.Dir, serviceSwitchPending)); err != nil {
			return err
		}
		return syncServiceDirectory(s.Dir)
	}
	return nil
}

func (s *Store) readLaunchAgentSwitch(key *signing.Key, id string) ([]byte, LaunchAgentSwitch, error) {
	var empty LaunchAgentSwitch
	decoded, err := hex.DecodeString(id)
	if err != nil || len(decoded) != 32 || hex.EncodeToString(decoded) != id {
		return nil, empty, errors.New("state: invalid service switch id")
	}
	raw, err := readInitializationFile(filepath.Join(s.Dir, "service-switches", id+".json"))
	if err != nil {
		return nil, empty, err
	}
	hash := sha256.Sum256(raw)
	if hex.EncodeToString(hash[:]) != id {
		return nil, empty, errors.New("state: service switch identity mismatch")
	}
	p, err := s.validateLaunchAgentSwitch(key, raw)
	if err != nil {
		return nil, empty, err
	}
	return raw, p, nil
}

// ReadLaunchAgentSwitch returns an authenticated immutable journal for recovery.
func (s *Store) ReadLaunchAgentSwitch(key *signing.Key, id string) (LaunchAgentSwitch, error) {
	_, p, err := s.readLaunchAgentSwitch(key, id)
	return p, err
}
