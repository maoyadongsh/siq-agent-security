package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

func rotationFixture(t *testing.T) (*State, CredentialRotationRequest, string) {
	t.Helper()
	signer, err := NewSigner()
	if err != nil {
		t.Fatal(err)
	}
	pub, err := signer.PublicKeyPEM()
	if err != nil {
		t.Fatal(err)
	}
	state := &State{DeviceIdentity: "fixture-device", EnvironmentID: "fixture-env", Secret: "edge-" + strings.Repeat("a", 43),
		SignerSeed: signer.SeedB64(), PublicKeyPEM: pub}
	body, next, err := prepareCredentialRotation(state)
	if err != nil {
		t.Fatal(err)
	}
	return state, body, next
}

func rotationResponse(body CredentialRotationRequest) map[string]any {
	return map[string]any{"schema_version": "edge-credential-rotation-result/v1", "edge_agent_id": "fixture-edge",
		"environment_id": body.Environment, "rotation_id": body.RotationID, "status": "rotated", "runtime_permissions_changed": false}
}

func TestRotationPreparationSignsExactScopeWithoutMutatingState(t *testing.T) {
	state, body, next := rotationFixture(t)
	if state.Secret == next || len(next) != 48 || body.NewHash != rotationHash(next) || body.ExpectedHash != rotationHash(state.Secret) {
		t.Fatal("credential scope mismatch")
	}
	payload, err := body.signedBytes()
	if err != nil || VerifySignature(state.PublicKeyPEM, payload, body.Signature) != nil {
		t.Fatal("signature failed")
	}
	for _, secret := range []string{state.Secret, next, state.SignerSeed} {
		if strings.Contains(string(payload), secret) {
			t.Fatal("secret in signed payload")
		}
	}
	second, secondSecret, err := prepareCredentialRotation(state)
	if err != nil || second.RotationID == body.RotationID || secondSecret == next {
		t.Fatal("randomness not independent")
	}
	body.Environment = "foreign-env"
	changed, _ := body.signedBytes()
	if VerifySignature(state.PublicKeyPEM, changed, body.Signature) == nil {
		t.Fatal("scope mutation accepted")
	}
}

func TestRotationTransportAndNewCredentialRecovery(t *testing.T) {
	state, body, next := rotationFixture(t)
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Method != "POST" || r.URL.Path != "/edge/v1/credential-rotation" || r.Header.Get("X-Edge-Identity") != body.Identity {
			t.Error("wrong route")
		}
		expected := state.Secret
		if calls == 2 {
			expected = next
		}
		if r.Header.Get("Authorization") != "Bearer "+expected {
			t.Error("wrong credential")
		}
		var received CredentialRotationRequest
		if json.NewDecoder(r.Body).Decode(&received) != nil || received != body {
			t.Error("body changed")
		}
		json.NewEncoder(w).Encode(rotationResponse(body))
	}))
	defer server.Close()
	for _, secret := range []string{state.Secret, next} {
		client := NewClient(ClientConfig{ControlPlaneURL: server.URL, DeviceIdentity: state.DeviceIdentity, Secret: secret})
		result, err := client.RotateCredential(context.Background(), body)
		if err != nil || result.Status != "rotated" {
			t.Fatal("rotation not accepted", err)
		}
	}
	if calls != 2 || state.Secret == next {
		t.Fatal("implicit retry or activation")
	}
}

func TestRotationRejectsUntrustedResponses(t *testing.T) {
	for _, mode := range []string{"foreign", "key", "status", "runtime", "missing", "extra", "duplicate", "case", "oversized", "trailing", "server-error", "unauthorized"} {
		t.Run(mode, func(t *testing.T) {
			state, body, _ := rotationFixture(t)
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				result := rotationResponse(body)
				switch mode {
				case "foreign":
					result["environment_id"] = "other"
				case "key":
					result["rotation_id"] = "other"
				case "status":
					result["status"] = "active"
				case "runtime":
					result["runtime_permissions_changed"] = true
				case "missing":
					delete(result, "runtime_permissions_changed")
				case "extra":
					result["secret"] = state.Secret
				case "case":
					result["Status"] = result["status"]
					delete(result, "status")
				case "oversized":
					io.WriteString(w, strings.Repeat(" ", 4097))
					return
				case "server-error":
					w.WriteHeader(503)
					io.WriteString(w, state.Secret)
					return
				case "unauthorized":
					w.WriteHeader(401)
					io.WriteString(w, state.Secret)
					return
				}
				raw, _ := json.Marshal(result)
				if mode == "duplicate" {
					raw = []byte(`{"status":"rotated",` + string(raw[1:]))
				}
				if mode == "trailing" {
					raw = append(raw, []byte(`{}`)...)
				}
				w.Write(raw)
			}))
			defer server.Close()
			client := NewClient(ClientConfig{ControlPlaneURL: server.URL, DeviceIdentity: state.DeviceIdentity, Secret: state.Secret})
			result, err := client.RotateCredential(context.Background(), body)
			if err == nil || result != nil || calls != 1 {
				t.Fatal("bad response accepted or retried")
			}
			if strings.Contains(err.Error(), state.Secret) {
				t.Fatal("secret leaked")
			}
		})
	}
}

func TestRotationDoesNotFollowRedirects(t *testing.T) {
	state, body, _ := rotationFixture(t)
	forwarded := 0
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { forwarded++ }))
	defer target.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, target.URL, 307) }))
	defer server.Close()
	client := NewClient(ClientConfig{ControlPlaneURL: server.URL, DeviceIdentity: state.DeviceIdentity, Secret: state.Secret})
	if _, err := client.RotateCredential(context.Background(), body); err == nil || forwarded != 0 {
		t.Fatal("redirect followed")
	}
}

func TestRotationInvalidLocalIdentityNeverSends(t *testing.T) {
	state, body, _ := rotationFixture(t)
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls++ }))
	defer server.Close()
	client := NewClient(ClientConfig{ControlPlaneURL: server.URL, DeviceIdentity: "foreign", Secret: state.Secret})
	if _, err := client.RotateCredential(context.Background(), body); err == nil || calls != 0 {
		t.Fatal("identity mismatch sent")
	}
	state.PublicKeyPEM = "wrong key"
	if _, _, err := prepareCredentialRotation(state); err == nil {
		t.Fatal("key mismatch accepted")
	}
}

func TestRotationIndependentPythonVector(t *testing.T) {
	raw, err := os.ReadFile("../../packages/contracts/fixtures/credential_rotation_vector_v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var vector struct {
		Scope     string                    `json:"scope"`
		Seed      string                    `json:"seed_base64"`
		Request   CredentialRotationRequest `json:"request"`
		Canonical string                    `json:"canonical"`
	}
	if json.Unmarshal(raw, &vector) != nil || vector.Scope != "public-test-key-only" {
		t.Fatal("invalid vector")
	}
	canonical, err := vector.Request.signedBytes()
	if err != nil || string(canonical) != vector.Canonical {
		t.Fatal("canonical bytes diverged")
	}
	signer, err := NewSignerFromSeed(vector.Seed)
	if err != nil {
		t.Fatal(err)
	}
	signature, err := signer.Sign(canonical)
	if err != nil || signature != vector.Request.Signature {
		t.Fatal("signature diverged")
	}
}
