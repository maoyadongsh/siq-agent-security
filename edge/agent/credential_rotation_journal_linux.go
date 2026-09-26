//go:build linux

package main

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
)

// The old credential remains in state.json. This journal contains only the new
// credential, exact signed request, and a digest binding all other state fields.
// Callers must hold the task lock throughout preparation, transport and recovery.
type credentialRotationJournal struct {
	Schema    string                    `json:"schema_version"`
	Baseline  string                    `json:"state_baseline"`
	NewSecret string                    `json:"new_secret"`
	Request   CredentialRotationRequest `json:"request"`
}

func rotationStateBaseline(state *State) string {
	copy := *state
	copy.Secret = ""
	raw, err := json.Marshal(copy)
	if err != nil {
		return ""
	}
	return rotationHash(string(raw))
}

func (j *credentialRotationJournal) validate(state *State) error {
	if state == nil || j.Schema != "edge-credential-rotation-pending/v1" ||
		j.Baseline == "" || j.Baseline != rotationStateBaseline(state) ||
		!j.Request.valid() || j.Request.Identity != state.DeviceIdentity ||
		j.Request.Environment != state.EnvironmentID || len(j.NewSecret) != 48 ||
		rotationHash(j.NewSecret) != j.Request.NewHash ||
		(rotationHash(state.Secret) != j.Request.ExpectedHash && state.Secret != j.NewSecret) {
		return errRotation
	}
	payload, err := j.Request.signedBytes()
	if err != nil || VerifySignature(state.PublicKeyPEM, payload, j.Request.Signature) != nil {
		return errRotation
	}
	return nil
}

func rotationJournalPath() (string, error) {
	dir, err := StateDir()
	if err != nil {
		return "", errRotation
	}
	return filepath.Join(dir, "credential-rotation-pending.json"), nil
}

func readRotationJournal(state *State) (*credentialRotationJournal, error) {
	path, err := rotationJournalPath()
	if err != nil {
		return nil, errRotation
	}
	// Reuse the pinned ancestor, owner/mode/link and duplicate-JSON checks.
	raw, err := readDeviceState(path)
	if err != nil || len(raw) > 8192 {
		return nil, errRotation
	}
	fields, ok := rotationJSONFields(raw, []string{"schema_version", "state_baseline", "new_secret", "request"}, true)
	if !ok {
		return nil, errRotation
	}
	if _, ok := rotationJSONFields(fields["request"], []string{"schema_version", "device_identity", "environment_id", "rotation_id", "expected_secret_hash", "new_secret_hash", "signature"}, true); !ok {
		return nil, errRotation
	}
	var journal credentialRotationJournal
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&journal) != nil || decoder.Decode(new(any)) != io.EOF || journal.validate(state) != nil {
		return nil, errRotation
	}
	return &journal, nil
}

// A failed write deliberately leaves the partial journal for review. Never send
// a request until this function has returned a durably persisted journal.
func prepareRotationJournal(state *State) (*credentialRotationJournal, error) {
	current, err := loadRotationState()
	if err != nil || state == nil || rotationStateBaseline(current) != rotationStateBaseline(state) || current.Secret != state.Secret {
		return nil, errRotation
	}
	if NewClient(ClientConfig{ControlPlaneURL: state.ControlPlaneURL, DeviceIdentity: state.DeviceIdentity, Secret: state.Secret, Version: "rotation"}).configErr != nil {
		return nil, errRotation
	}
	request, secret, err := prepareCredentialRotation(state)
	if err != nil {
		return nil, errRotation
	}
	journal := &credentialRotationJournal{Schema: "edge-credential-rotation-pending/v1", Baseline: rotationStateBaseline(state), NewSecret: secret, Request: request}
	if journal.validate(state) != nil {
		return nil, errRotation
	}
	raw, err := json.Marshal(journal)
	if err != nil {
		return nil, errRotation
	}
	path, err := rotationJournalPath()
	if err != nil {
		return nil, errRotation
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return nil, errRotation
	}
	n, writeErr := file.Write(raw)
	syncErr := file.Sync()
	closeErr := file.Close()
	if writeErr != nil || n != len(raw) || syncErr != nil || closeErr != nil || syncRegistrationDirectory(filepath.Dir(path)) != nil {
		return nil, errRotation
	}
	return readRotationJournal(state)
}
