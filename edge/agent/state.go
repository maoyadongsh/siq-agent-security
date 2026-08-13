package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// ErrNotRegistered is returned by LoadState when the agent has no local state.
var ErrNotRegistered = errors.New("agent is not registered: run 'register' first")

// State is the locally persisted agent identity and control-plane secret.
// Security invariants:
//   - the file is written with mode 0600 and its directory with 0700;
//   - the secret is never logged and never leaves the process except as the
//     Authorization: Bearer header of control-plane calls;
//   - writes are atomic (temp file + rename) so a crashed agent cannot leave
//     a half-written state file.
type State struct {
	ControlPlaneURL string `json:"control_plane_url"`
	DeviceIdentity  string `json:"device_identity"`
	Secret          string `json:"secret"`
	PublicKeyPEM    string `json:"public_key_pem,omitempty"`
}

// StateDir returns SIQ_EDGE_STATE_DIR or ~/.siq-edge.
func StateDir() (string, error) {
	if d := os.Getenv("SIQ_EDGE_STATE_DIR"); d != "" {
		return d, nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("state: cannot resolve home directory: %w", err)
	}
	return filepath.Join(home, ".siq-edge"), nil
}

// StateFilePath returns the absolute path of the state file.
func StateFilePath() (string, error) {
	dir, err := StateDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "state.json"), nil
}

// LoadState reads the state file. A missing file maps to ErrNotRegistered.
func LoadState() (*State, error) {
	p, err := StateFilePath()
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(p)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, ErrNotRegistered
		}
		return nil, fmt.Errorf("state: read %s: %w", p, err)
	}
	var s State
	if err := json.Unmarshal(data, &s); err != nil {
		return nil, fmt.Errorf("state: parse %s: %w", p, err)
	}
	if s.DeviceIdentity == "" || s.Secret == "" {
		return nil, fmt.Errorf("state: %s is incomplete (device_identity/secret missing)", p)
	}
	return &s, nil
}

// Save writes the state file atomically with mode 0600.
func (s *State) Save() error {
	dir, err := StateDir()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("state: mkdir %s: %w", dir, err)
	}
	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return fmt.Errorf("state: encode: %w", err)
	}
	p := filepath.Join(dir, "state.json")
	tmp, err := os.CreateTemp(dir, ".state-*.tmp")
	if err != nil {
		return fmt.Errorf("state: create temp file: %w", err)
	}
	cleanup := func() {
		tmp.Close()
		os.Remove(tmp.Name())
	}
	if err := tmp.Chmod(0o600); err != nil {
		cleanup()
		return fmt.Errorf("state: chmod temp file: %w", err)
	}
	if _, err := tmp.Write(data); err != nil {
		cleanup()
		return fmt.Errorf("state: write temp file: %w", err)
	}
	if err := tmp.Sync(); err != nil {
		cleanup()
		return fmt.Errorf("state: sync temp file: %w", err)
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmp.Name())
		return fmt.Errorf("state: close temp file: %w", err)
	}
	if err := os.Rename(tmp.Name(), p); err != nil {
		os.Remove(tmp.Name())
		return fmt.Errorf("state: rename temp file: %w", err)
	}
	return nil
}
