//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"os"
	"path/filepath"
)

// Refuse state produced by an unknown newer schema rather than dropping fields
// when activating credentials through State.Save.
func loadRotationState() (*State, error) {
	path, err := StateFilePath()
	if err != nil {
		return nil, errRotation
	}
	raw, err := readDeviceState(path)
	if err != nil {
		return nil, errRotation
	}
	if _, ok := rotationJSONFields(raw, []string{"control_plane_url", "device_identity", "secret", "public_key_pem", "control_plane_public_key", "environment_id", "signer_seed", "discovery_plan", "discovery_plan_sha256"}, false); !ok {
		return nil, errRotation
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	var state State
	if decoder.Decode(&state) != nil || decoder.Decode(new(any)) != io.EOF || state.DeviceIdentity == "" || state.Secret == "" {
		return nil, errRotation
	}
	return &state, nil
}

func cmdRotateCredential(ctx context.Context, args []string) error {
	fs := flag.NewFlagSet("rotate-credential", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	confirm := fs.String("confirm-device", "", "device identity to confirm")
	resume := fs.Bool("resume", false, "resume the exact pending request")
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return nil
		}
		return errRotation
	}
	if *confirm == "" || fs.NArg() != 0 {
		return errRotation
	}
	unlock, err := acquireTaskLock()
	if err != nil {
		return errRotation
	}
	defer unlock()
	state, err := loadRotationState()
	if err != nil || state.DeviceIdentity != *confirm {
		return errRotation
	}
	var journal *credentialRotationJournal
	if *resume {
		journal, err = readRotationJournal(state)
	} else {
		journal, err = prepareRotationJournal(state)
	}
	if err != nil {
		return errRotation
	}
	secret := state.Secret
	if *resume {
		secret = journal.NewSecret
	}
	client := func(secret string) *Client {
		return NewClient(ClientConfig{ControlPlaneURL: state.ControlPlaneURL, DeviceIdentity: state.DeviceIdentity, Secret: secret, Version: agentVersion})
	}
	_, err = client(secret).RotateCredential(ctx, journal.Request)
	if *resume && errors.Is(err, errRotationAuth) && state.Secret != journal.NewSecret {
		_, err = client(state.Secret).RotateCredential(ctx, journal.Request)
	}
	if err != nil {
		return errRotation
	}
	return activateRotation(state, journal, rotationFileOps{
		save: (*State).Save, syncDir: syncRegistrationDirectory, remove: os.Remove,
	})
}

// Internal, per-call fault seams; never controlled by flags or environment.
type rotationFileOps struct {
	save    func(*State) error
	syncDir func(string) error
	remove  func(string) error
}

var errRotationCleanup = errors.New("credential_rotation_activated; cleanup_durability_unconfirmed; keep current state, inspect pending journal before any further rotation")

// Only call after the control plane has confirmed the exact rotation request,
// while still holding the task lock.
func activateRotation(state *State, journal *credentialRotationJournal, files rotationFileOps) error {
	if state == nil || journal == nil || files.save == nil || files.syncDir == nil || files.remove == nil {
		return errRotation
	}
	current, err := loadRotationState()
	if err != nil || journal.validate(current) != nil || current.Secret != state.Secret {
		return errRotation
	}
	stored, err := readRotationJournal(current)
	if err != nil || *stored != *journal {
		return errRotation
	}
	current.Secret = journal.NewSecret
	if files.save(current) != nil {
		return errRotation
	}
	path, err := rotationJournalPath()
	if err != nil || files.syncDir(filepath.Dir(path)) != nil {
		return errRotation
	}
	activated, err := loadRotationState()
	if err != nil || journal.validate(activated) != nil || activated.Secret != journal.NewSecret {
		return errRotation
	}
	// Only remove the already validated pending record after durable activation.
	stored, err = readRotationJournal(current)
	if err != nil || *stored != *journal {
		return errRotation
	}
	if files.remove(path) != nil {
		return errRotation
	}
	if files.syncDir(filepath.Dir(path)) != nil {
		return errRotationCleanup
	}
	return nil
}
