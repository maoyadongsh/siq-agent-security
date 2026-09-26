package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
)

var errRegistrationPending = errors.New("registration_pending; preserve identity and resolve prior attempt before registering again")

// Persist the signing identity BEFORE consuming an enrollment code. No code or
// credential is stored here. O_EXCL prevents two registrars claiming the same
// local state. Even a partial journal blocks retry; never delete it on failure.
func beginRegistration(state *State) error {
	dir, err := StateDir()
	if err != nil {
		return errRegistrationPending
	}
	if err := os.MkdirAll(dir, 0700); err != nil {
		return errRegistrationPending
	}
	info, err := os.Lstat(dir)
	if err != nil || !info.IsDir() || info.Mode().Perm()&0077 != 0 {
		return errRegistrationPending
	}
	data, err := json.Marshal(struct {
		Schema              string `json:"schema_version"`
		ControlPlane        string `json:"control_plane_url"`
		Identity            string `json:"device_identity"`
		PublicKey           string `json:"public_key_pem"`
		Seed                string `json:"signer_seed"`
		ExpectedEnvironment string `json:"expected_environment_id,omitempty"`
	}{"edge-registration-pending/v1", state.ControlPlaneURL, state.DeviceIdentity, state.PublicKeyPEM, state.SignerSeed, state.EnvironmentID})
	if err != nil {
		return errRegistrationPending
	}
	f, err := os.OpenFile(filepath.Join(dir, "registration-pending.json"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return errRegistrationPending
	}
	defer f.Close()
	if n, err := f.Write(data); err != nil || n != len(data) {
		return errRegistrationPending
	}
	if f.Sync() != nil {
		return errRegistrationPending
	}
	return syncRegistrationDirectory(dir)
}
