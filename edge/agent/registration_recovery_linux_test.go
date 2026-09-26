//go:build linux

package main

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"

	"siq-agent-security/edge/agent/canon"
)

func TestNativeRegistrationRecoveryResponseLoss(t *testing.T) {
	parent := t.TempDir()
	if err := os.Chmod(parent, 0700); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(parent, "private")
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	signer, err := NewSigner()
	if err != nil {
		t.Fatal(err)
	}
	pub, err := signer.PublicKeyPEM()
	if err != nil {
		t.Fatal(err)
	}
	var calls atomic.Int32
	var firstDigest string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/edge/v1/registration-recovery" {
			t.Error("wrong route")
		}
		call := calls.Add(1)
		var body map[string]any
		if json.NewDecoder(r.Body).Decode(&body) != nil {
			t.Error("invalid request")
			return
		}
		sig, _ := body["signature"].(string)
		delete(body, "signature")
		payload, err := canon.Marshal(body)
		if err != nil || VerifySignature(pub, payload, sig) != nil {
			t.Error("invalid proof")
		}
		var credential recoveryCredential
		if readRecoveryFile(filepath.Join(dir, "registration-recovery.json"), &credential) != nil {
			t.Error("credential not durable before request")
		}
		h := sha256.Sum256([]byte(credential.Secret))
		digest := hex.EncodeToString(h[:])
		if body["secret_hash"] != digest || body["environment_id"] != "env-fixture" || body["device_identity"] != "edge-fixture" {
			t.Error("request not bound to saved identity")
		}
		if call == 1 {
			firstDigest = digest
			w.WriteHeader(503)
			return
		}
		if digest != firstDigest {
			t.Error("retry changed credential")
		}
		_ = json.NewEncoder(w).Encode(map[string]string{"schema_version": "edge-registration-recovery/v1", "edge_agent_id": "edge-fixture", "environment_id": "env-fixture", "control_plane_public_key": base64.StdEncoding.EncodeToString(make([]byte, 32)), "status": "recovered"})
	}))
	defer server.Close()
	if beginRegistration(&State{ControlPlaneURL: server.URL, DeviceIdentity: "edge-fixture", PublicKeyPEM: pub, SignerSeed: signer.SeedB64()}) != nil {
		t.Fatal("pending fixture")
	}
	args := []string{"--control-plane", server.URL, "--environment", "env-fixture"}
	if cmdRecoverRegistration(context.Background(), args) != errRecovery || calls.Load() != 1 {
		t.Fatal("first attempt must remain pending without retry")
	}
	if _, err := os.Stat(filepath.Join(dir, "state.json")); !os.IsNotExist(err) {
		t.Fatal("failed attempt created active state")
	}
	if err := cmdRecoverRegistration(context.Background(), args); err != nil {
		t.Fatal("retry failed")
	}
	state, err := LoadState()
	if err != nil || state.EnvironmentID != "env-fixture" || state.DeviceIdentity != "edge-fixture" || state.SignerSeed != signer.SeedB64() {
		t.Fatal("recovered identity changed", err)
	}
	h := sha256.Sum256([]byte(state.Secret))
	if hex.EncodeToString(h[:]) != firstDigest {
		t.Fatal("recovered credential mismatch")
	}
	if cmdRecoverRegistration(context.Background(), args) != errRecovery || calls.Load() != 2 {
		t.Fatal("existing identity overwritten")
	}
}

func TestRecoveryContextMismatchDoesNotCreateCredential(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "private")
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	signer, _ := NewSigner()
	pub, _ := signer.PublicKeyPEM()
	if beginRegistration(&State{ControlPlaneURL: "https://expected.example.test", DeviceIdentity: "edge-fixture", PublicKeyPEM: pub, SignerSeed: signer.SeedB64(), EnvironmentID: "env-fixture"}) != nil {
		t.Fatal("pending fixture")
	}
	if cmdRecoverRegistration(context.Background(), []string{"--control-plane", "https://other.example.test", "--environment", "env-fixture"}) != errRecovery {
		t.Fatal("origin mismatch accepted")
	}
	if _, err := os.Stat(filepath.Join(dir, "registration-recovery.json")); !os.IsNotExist(err) {
		t.Fatal("mismatch created credential")
	}
	if cmdRecoverRegistration(context.Background(), []string{"--control-plane", "https://expected.example.test", "--environment", "env-other"}) != errRecovery {
		t.Fatal("saved environment expectation ignored during recovery")
	}
	if _, err := os.Stat(filepath.Join(dir, "registration-recovery.json")); !os.IsNotExist(err) {
		t.Fatal("environment mismatch created credential")
	}
}
