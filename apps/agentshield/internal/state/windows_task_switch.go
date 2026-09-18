package state

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/stateformat"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

const windowsTaskSwitchSchema = "local-windows-task-switch/v1"

// WindowsTaskSwitch authenticates both sides of a current-user task change.
// It does not establish release authenticity or permission to run either file.
type WindowsTaskSwitch struct {
	TransactionNonce string                `json:"transaction_nonce"`
	BinaryBindings   ServiceBinaryBindings `json:"binary_bindings"`
	SchemaVersion    string                `json:"schema_version"`
	SourceRecord     WindowsTaskRecord     `json:"source_record"`
	TargetRecord     WindowsTaskRecord     `json:"target_record"`
	SourceXML        string                `json:"source_xml"`
	TargetXML        string                `json:"target_xml"`
	Signature        string                `json:"signature"`
}

func (p WindowsTaskSwitch) unsigned() (map[string]any, error) {
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

// PrepareWindowsTaskSwitch publishes an immutable journal and startup barrier.
// The caller must hold service-control and first confirm the source is idle.
func (s *Store) PrepareWindowsTaskSwitch(w *Writer, key *signing.Key, source, target []byte, sid string, bindings ServiceBinaryBindings) (string, error) {
	if !bindings.valid() {
		return "", errors.New("state: invalid service binary bindings")
	}
	if err := s.serviceWriter(w); err != nil {
		return "", err
	}
	if err := s.CheckServiceSwitchPending(); err != nil {
		return "", err
	}
	before, err := s.VerifyWindowsTask(key, source, sid)
	if err != nil {
		return "", err
	}
	after, err := s.expectedWindowsTask(key, target, sid)
	if err != nil {
		return "", err
	}
	if bytes.Equal(source, target) {
		return "", errors.New("state: Windows task switch has no change")
	}
	after.Signature, err = key.SignCanonical(after.unsigned())
	if err != nil {
		return "", err
	}
	var nonce [16]byte
	if _, err = rand.Read(nonce[:]); err != nil {
		return "", err
	}
	p := WindowsTaskSwitch{TransactionNonce: hex.EncodeToString(nonce[:]), BinaryBindings: bindings, SchemaVersion: windowsTaskSwitchSchema, SourceRecord: before, TargetRecord: after, SourceXML: string(source), TargetXML: string(target)}
	doc, err := p.unsigned()
	if err != nil {
		return "", err
	}
	p.Signature, err = key.SignCanonical(doc)
	if err != nil {
		return "", err
	}
	raw, err := json.Marshal(p)
	if err != nil {
		return "", err
	}
	if _, err = s.validateWindowsTaskSwitch(key, raw); err != nil {
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

func (s *Store) validateWindowsTaskSwitch(key *signing.Key, raw []byte) (WindowsTaskSwitch, error) {
	var p WindowsTaskSwitch
	fields := []string{"transaction_nonce", "binary_bindings", "schema_version", "source_record", "target_record", "source_xml", "target_xml", "signature"}
	if key == nil || len(raw) > 65536 || stateformat.DecodeObject(raw, fields, &p) != nil {
		return p, errors.New("state: invalid Windows task switch")
	}
	var nested map[string]json.RawMessage
	if err := json.Unmarshal(raw, &nested); err != nil {
		return p, err
	}
	if stateformat.DecodeObject(nested["binary_bindings"], []string{"source_sha256", "target_sha256"}, &p.BinaryBindings) != nil {
		return p, errors.New("state: invalid Windows task switch bindings")
	}
	recordFields := []string{"schema_version", "instance_id", "state_directory_id", "task_name", "xml_sha256", "user_sid", "signature"}
	if stateformat.DecodeObject(nested["source_record"], recordFields, &p.SourceRecord) != nil || stateformat.DecodeObject(nested["target_record"], recordFields, &p.TargetRecord) != nil {
		return p, errors.New("state: invalid Windows task switch records")
	}
	if p.SchemaVersion != windowsTaskSwitchSchema || !p.BinaryBindings.valid() {
		return p, errors.New("state: invalid Windows task switch schema or bindings")
	}
	nonce, nonceErr := hex.DecodeString(p.TransactionNonce)
	if nonceErr != nil || len(nonce) != 16 || hex.EncodeToString(nonce) != p.TransactionNonce {
		return p, errors.New("state: invalid Windows task switch nonce")
	}
	doc, err := p.unsigned()
	if err != nil || !canonicalWindowsSwitchSignature(p.Signature) || !signing.VerifyCanonical(key.Public(), doc, p.Signature) {
		return p, errors.New("state: invalid Windows task switch signature")
	}
	for _, pair := range []struct {
		record WindowsTaskRecord
		xml    string
	}{{p.SourceRecord, p.SourceXML}, {p.TargetRecord, p.TargetXML}} {
		if !canonicalWindowsSwitchSignature(pair.record.Signature) {
			return p, errors.New("state: invalid Windows task record signature encoding")
		}
		expected, err := s.expectedWindowsTask(key, []byte(pair.xml), pair.record.UserSID)
		if err != nil {
			return p, err
		}
		raw, err := json.Marshal(pair.record)
		if err != nil {
			return p, err
		}
		if _, err = verifyWindowsTaskRecord(raw, key, expected); err != nil {
			return p, err
		}
	}
	if p.SourceXML == p.TargetXML || p.SourceRecord.TaskName != p.TargetRecord.TaskName || p.SourceRecord.UserSID != p.TargetRecord.UserSID {
		return p, errors.New("state: empty or rebound Windows task switch")
	}
	return p, nil
}

func canonicalWindowsSwitchSignature(value string) bool {
	raw, err := hex.DecodeString(value)
	return err == nil && len(raw) == 64 && hex.EncodeToString(raw) == value
}

func (s *Store) readWindowsTaskSwitch(key *signing.Key, id string) ([]byte, WindowsTaskSwitch, error) {
	var empty WindowsTaskSwitch
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
	p, err := s.validateWindowsTaskSwitch(key, raw)
	return raw, p, err
}

// ReadWindowsTaskSwitch authenticates an archived transaction without changing it.
func (s *Store) ReadWindowsTaskSwitch(key *signing.Key, id string) (WindowsTaskSwitch, error) {
	_, p, err := s.readWindowsTaskSwitch(key, id)
	return p, err
}

// windowsTaskSwitchEvidence rejects conflicting markers even if the other one
// is valid. A done marker with a remaining pending marker still blocks startup.
func (s *Store) windowsTaskSwitchEvidence(id string, raw []byte) (pending, done bool, err error) {
	for _, marker := range []struct {
		path    string
		present *bool
	}{
		{filepath.Join(s.Dir, serviceSwitchPending), &pending},
		{filepath.Join(s.Dir, "service-switches", id+".done.json"), &done},
	} {
		value, e := readInitializationFile(marker.path)
		if errors.Is(e, os.ErrNotExist) {
			continue
		}
		if e != nil || !bytes.Equal(value, raw) {
			return false, false, errors.New("state: another or invalid Windows task switch marker")
		}
		*marker.present = true
	}
	if !pending && !done {
		return false, false, errors.New("state: Windows task switch not pending or completed")
	}
	return pending, done, nil
}

type windowsTaskImage struct {
	path          string
	before, after []byte
}

func (s *Store) windowsTaskSwitchImages(p WindowsTaskSwitch) []windowsTaskImage {
	before, _ := json.Marshal(p.SourceRecord)
	after, _ := json.Marshal(p.TargetRecord)
	return []windowsTaskImage{
		{filepath.Join(s.Dir, strings.TrimPrefix(p.SourceRecord.TaskName, `\`)+".xml"), []byte(p.SourceXML), []byte(p.TargetXML)},
		{filepath.Join(s.Dir, "windows-task.json"), before, after},
	}
}

func validateWindowsTaskImages(images []windowsTaskImage, targetOnly bool) error {
	for _, image := range images {
		current, err := readInitializationFile(image.path)
		if err != nil {
			return err
		}
		if !bytes.Equal(current, image.after) && (targetOnly || !bytes.Equal(current, image.before)) {
			return errors.New("state: Windows task switch input drift")
		}
	}
	return nil
}

// ApplyWindowsTaskSwitch accepts either recorded image for partial recovery.
// It never clears the startup barrier or declares the system task switched.
func (s *Store) ApplyWindowsTaskSwitch(w *Writer, key *signing.Key, id string) error {
	if err := s.serviceWriter(w); err != nil {
		return err
	}
	raw, p, err := s.readWindowsTaskSwitch(key, id)
	if err != nil {
		return err
	}
	_, done, err := s.windowsTaskSwitchEvidence(id, raw)
	if err != nil {
		return err
	}
	images := s.windowsTaskSwitchImages(p)
	if err = validateWindowsTaskImages(images, done); err != nil {
		return err
	}
	for _, image := range images {
		if err = replaceServiceImage(image.path, image.before, image.after); err != nil {
			return err
		}
	}
	return nil
}

// FinishWindowsTaskSwitch is called only after the caller verifies the target
// task is registered and idle while retaining both lifecycle and main Writers.
// Completion records configuration only; health must be checked after start.
func (s *Store) FinishWindowsTaskSwitch(w *Writer, key *signing.Key, id string) error {
	if err := s.serviceWriter(w); err != nil {
		return err
	}
	raw, p, err := s.readWindowsTaskSwitch(key, id)
	if err != nil {
		return err
	}
	pending, _, err := s.windowsTaskSwitchEvidence(id, raw)
	if err != nil {
		return err
	}
	if err = validateWindowsTaskImages(s.windowsTaskSwitchImages(p), true); err != nil {
		return err
	}
	if err = publishCommitFile(filepath.Join(s.Dir, "service-switches", id+".done.json"), raw); err != nil {
		return err
	}
	if pending {
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

// CheckWindowsTaskSwitchCompleted requires authenticated completion, no pending
// switch, and both exact target images. It is safe to call while the task runs.
func (s *Store) CheckWindowsTaskSwitchCompleted(key *signing.Key, id string) error {
	raw, p, err := s.readWindowsTaskSwitch(key, id)
	if err != nil {
		return err
	}
	pending, done, err := s.windowsTaskSwitchEvidence(id, raw)
	if err != nil {
		return err
	}
	if pending || !done {
		return errors.New("state: Windows task switch still pending")
	}
	return validateWindowsTaskImages(s.windowsTaskSwitchImages(p), true)
}

// CheckWindowsTaskSwitchRecovery validates all local before/after evidence prior
// to any external task mutation. It never repairs files or clears a barrier.
func (s *Store) CheckWindowsTaskSwitchRecovery(key *signing.Key, id string) error {
	raw, p, err := s.readWindowsTaskSwitch(key, id)
	if err != nil {
		return err
	}
	_, done, err := s.windowsTaskSwitchEvidence(id, raw)
	if err != nil {
		return err
	}
	return validateWindowsTaskImages(s.windowsTaskSwitchImages(p), done)
}
