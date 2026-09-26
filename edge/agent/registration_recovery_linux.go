//go:build linux

package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"syscall"

	"siq-agent-security/edge/agent/canon"
)

var errRecovery = errors.New("registration_recovery_failed; preserve local recovery files")

type pendingRegistration struct {
	Schema              string `json:"schema_version"`
	ControlPlane        string `json:"control_plane_url"`
	Identity            string `json:"device_identity"`
	PublicKey           string `json:"public_key_pem"`
	Seed                string `json:"signer_seed"`
	ExpectedEnvironment string `json:"expected_environment_id,omitempty"`
}

type recoveryCredential struct {
	Schema       string `json:"schema_version"`
	ControlPlane string `json:"control_plane_url"`
	Identity     string `json:"device_identity"`
	Environment  string `json:"environment_id"`
	Secret       string `json:"secret"`
}

func cmdRecoverRegistration(ctx context.Context, args []string) error {
	fs := flag.NewFlagSet("recover-registration", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	cp := fs.String("control-plane", "", "")
	environment := fs.String("environment", "", "")
	if err := fs.Parse(args); err != nil {
		return errRecovery
	}
	if fs.NArg() != 0 || !regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,64}$`).MatchString(*environment) {
		return errRecovery
	}
	if _, err := validateControlPlaneURL(*cp); err != nil {
		return errRecovery
	}
	unlock, err := acquireTaskLock()
	if err != nil {
		return errRecovery
	}
	defer unlock()
	statePath, err := StateFilePath()
	if err != nil {
		return errRecovery
	}
	if _, err := os.Lstat(statePath); !os.IsNotExist(err) {
		return errRecovery
	}
	dir, err := StateDir()
	if err != nil {
		return errRecovery
	}
	var pending pendingRegistration
	if readRecoveryFile(filepath.Join(dir, "registration-pending.json"), &pending) != nil || pending.Schema != "edge-registration-pending/v1" || pending.ControlPlane != *cp || !regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,128}$`).MatchString(pending.Identity) {
		return errRecovery
	}
	signer, err := NewSignerFromSeed(pending.Seed)
	if pending.ExpectedEnvironment != "" && pending.ExpectedEnvironment != *environment {
		return errRecovery
	}
	if err != nil {
		return errRecovery
	}
	pub, err := signer.PublicKeyPEM()
	if err != nil || pub != pending.PublicKey {
		return errRecovery
	}
	credentialPath := filepath.Join(dir, "registration-recovery.json")
	var credential recoveryCredential
	if _, err := os.Lstat(credentialPath); os.IsNotExist(err) {
		var random [32]byte
		if _, err := rand.Read(random[:]); err != nil {
			return errRecovery
		}
		credential = recoveryCredential{"edge-registration-recovery-local/v1", *cp, pending.Identity, *environment, "edge-recovery-" + hex.EncodeToString(random[:])}
		raw, err := json.Marshal(credential)
		if err != nil {
			return errRecovery
		}
		f, err := os.OpenFile(credentialPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return errRecovery
		}
		n, writeErr := f.Write(raw)
		syncErr := f.Sync()
		closeErr := f.Close()
		if writeErr != nil || n != len(raw) || syncErr != nil || closeErr != nil || syncRegistrationDirectory(dir) != nil {
			return errRecovery
		}
	}
	if readRecoveryFile(credentialPath, &credential) != nil || credential.Schema != "edge-registration-recovery-local/v1" || credential.ControlPlane != *cp || credential.Identity != pending.Identity || credential.Environment != *environment || !regexp.MustCompile(`^edge-recovery-[a-f0-9]{64}$`).MatchString(credential.Secret) {
		return errRecovery
	}
	h := sha256.Sum256([]byte(credential.Secret))
	body := map[string]any{"schema_version": "edge-registration-recovery/v1", "device_identity": pending.Identity, "environment_id": *environment, "secret_hash": hex.EncodeToString(h[:])}
	payload, err := canon.Marshal(body)
	if err != nil {
		return errRecovery
	}
	body["signature"], err = signer.Sign(payload)
	if err != nil {
		return errRecovery
	}
	var response struct {
		Schema      string `json:"schema_version"`
		EdgeID      string `json:"edge_agent_id"`
		Environment string `json:"environment_id"`
		ControlKey  string `json:"control_plane_public_key"`
		Status      string `json:"status"`
	}
	cli := NewClient(ClientConfig{ControlPlaneURL: *cp, Version: agentVersion})
	if cli.do(ctx, http.MethodPost, "/edge/v1/registration-recovery", body, &response, 0) != nil {
		return errRecovery
	}
	key, err := base64.StdEncoding.DecodeString(response.ControlKey)
	if err != nil || len(key) != 32 || response.Schema != "edge-registration-recovery/v1" || response.Environment != *environment || response.EdgeID == "" || response.Status != "recovered" {
		return errRecovery
	}
	state := &State{ControlPlaneURL: *cp, DeviceIdentity: pending.Identity, Secret: credential.Secret, PublicKeyPEM: pub, SignerSeed: pending.Seed, EnvironmentID: *environment, ControlPlanePublicKey: response.ControlKey}
	if state.Save() != nil || syncRegistrationDirectory(dir) != nil {
		return errRecovery
	}
	return nil
}

func readRecoveryFile(path string, target any) error {
	return readPrivateJSON(path, target, 8192)
}

func readPrivateJSON(path string, target any, limit int64) error {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0)
	if err != nil {
		return errRecovery
	}
	f := os.NewFile(uintptr(fd), "recovery-state")
	defer f.Close()
	var st syscall.Stat_t
	if syscall.Fstat(fd, &st) != nil || st.Mode&syscall.S_IFMT != syscall.S_IFREG || st.Mode&0077 != 0 || st.Nlink != 1 || int(st.Uid) != os.Geteuid() || st.Size > limit {
		return errRecovery
	}
	raw, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil || int64(len(raw)) > limit {
		return errRecovery
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(target) != nil {
		return errRecovery
	}
	if d.Decode(new(any)) != io.EOF {
		return errRecovery
	}
	return nil
}
