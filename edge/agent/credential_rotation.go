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
	"io"
	"net/http"
	"regexp"

	"siq-agent-security/edge/agent/canon"
)

var errRotation = errors.New("credential_rotation_unconfirmed; preserve pending credentials and request")
var errRotationAuth = errors.New("credential_rotation_authentication_denied; preserve pending credentials")

type CredentialRotationRequest struct {
	Schema       string `json:"schema_version"`
	Identity     string `json:"device_identity"`
	Environment  string `json:"environment_id"`
	RotationID   string `json:"rotation_id"`
	ExpectedHash string `json:"expected_secret_hash"`
	NewHash      string `json:"new_secret_hash"`
	Signature    string `json:"signature"`
}

type CredentialRotationResult struct {
	Schema                    string `json:"schema_version"`
	EdgeID                    string `json:"edge_agent_id"`
	Environment               string `json:"environment_id"`
	RotationID                string `json:"rotation_id"`
	Status                    string `json:"status"`
	RuntimePermissionsChanged *bool  `json:"runtime_permissions_changed"`
}

func rotationHash(secret string) string {
	digest := sha256.Sum256([]byte(secret))
	return hex.EncodeToString(digest[:])
}

func rotationResultFields(data []byte) bool {
	allowed := map[string]bool{"schema_version": true, "edge_agent_id": true, "environment_id": true,
		"rotation_id": true, "status": true, "runtime_permissions_changed": true}
	decoder := json.NewDecoder(bytes.NewReader(data))
	opening, err := decoder.Token()
	if err != nil || opening != json.Delim('{') {
		return false
	}
	for decoder.More() {
		key, err := decoder.Token()
		name, ok := key.(string)
		if err != nil || !ok || !allowed[name] {
			return false
		}
		delete(allowed, name)
		var value json.RawMessage
		if decoder.Decode(&value) != nil {
			return false
		}
	}
	closing, err := decoder.Token()
	return err == nil && closing == json.Delim('}') && len(allowed) == 0 && decoder.Decode(new(any)) == io.EOF
}

func (r CredentialRotationRequest) signedBytes() ([]byte, error) {
	return canon.Marshal(map[string]any{"schema_version": r.Schema, "device_identity": r.Identity,
		"environment_id": r.Environment, "rotation_id": r.RotationID,
		"expected_secret_hash": r.ExpectedHash, "new_secret_hash": r.NewHash})
}

func (r CredentialRotationRequest) valid() bool {
	return r.Schema == "edge-credential-rotation/v1" &&
		regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,128}$`).MatchString(r.Identity) &&
		regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,64}$`).MatchString(r.Environment) &&
		regexp.MustCompile(`^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$`).MatchString(r.RotationID) &&
		regexp.MustCompile(`^[a-f0-9]{64}$`).MatchString(r.ExpectedHash) &&
		regexp.MustCompile(`^[a-f0-9]{64}$`).MatchString(r.NewHash) && r.ExpectedHash != r.NewHash &&
		regexp.MustCompile(`^[a-f0-9]{128}$`).MatchString(r.Signature)
}

// Preparation does not persist or send anything. The caller MUST durably save the
// new secret and this exact request before invoking RotateCredential.
func prepareCredentialRotation(state *State) (CredentialRotationRequest, string, error) {
	if state == nil || len(state.Secret) < 32 {
		return CredentialRotationRequest{}, "", errRotation
	}
	signer, err := NewSignerFromSeed(state.SignerSeed)
	if err != nil {
		return CredentialRotationRequest{}, "", errRotation
	}
	pub, err := signer.PublicKeyPEM()
	if err != nil || pub != state.PublicKeyPEM {
		return CredentialRotationRequest{}, "", errRotation
	}
	var random [48]byte
	if _, err := rand.Read(random[:]); err != nil {
		return CredentialRotationRequest{}, "", errRotation
	}
	secret := "edge-" + base64.RawURLEncoding.EncodeToString(random[:32])
	// RFC 4122 UUID v4, with randomness independent of the new credential bytes.
	random[38] = random[38]&0x0f | 0x40
	random[40] = random[40]&0x3f | 0x80
	identifier := hex.EncodeToString(random[32:])
	id := identifier[:8] + "-" + identifier[8:12] + "-" + identifier[12:16] + "-" + identifier[16:20] + "-" + identifier[20:]
	request := CredentialRotationRequest{Schema: "edge-credential-rotation/v1", Identity: state.DeviceIdentity,
		Environment: state.EnvironmentID, RotationID: id, ExpectedHash: rotationHash(state.Secret), NewHash: rotationHash(secret)}
	payload, err := request.signedBytes()
	if err != nil {
		return CredentialRotationRequest{}, "", errRotation
	}
	request.Signature, err = signer.Sign(payload)
	if err != nil || !request.valid() {
		return CredentialRotationRequest{}, "", errRotation
	}
	return request, secret, nil
}

// RotateCredential is one explicit transport attempt, with no retries, redirect
// following, credential activation, or response-body error logging.
func (c *Client) RotateCredential(ctx context.Context, body CredentialRotationRequest) (*CredentialRotationResult, error) {
	if c.configErr != nil || !body.valid() || body.Identity != c.identity ||
		(rotationHash(c.secret) != body.ExpectedHash && rotationHash(c.secret) != body.NewHash) {
		return nil, errRotation
	}
	raw, err := json.Marshal(body)
	if err != nil {
		return nil, errRotation
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+"/edge/v1/credential-rotation", bytes.NewReader(raw))
	if err != nil {
		return nil, errRotation
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Edge-Identity", c.identity)
	req.Header.Set("X-Edge-Version", c.version)
	req.Header.Set("Authorization", "Bearer "+c.secret)
	transport := *c.http
	transport.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	resp, err := transport.Do(req)
	if err != nil {
		return nil, errRotation
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusUnauthorized {
		return nil, errRotationAuth
	}
	if resp.StatusCode != http.StatusOK {
		return nil, errRotation
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, 4097))
	if err != nil || len(data) > 4096 || !rotationResultFields(data) {
		return nil, errRotation
	}
	var result CredentialRotationResult
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&result) != nil || decoder.Decode(new(any)) != io.EOF {
		return nil, errRotation
	}
	if result.Schema != "edge-credential-rotation-result/v1" || result.Environment != body.Environment ||
		result.RotationID != body.RotationID || result.Status != "rotated" ||
		!regexp.MustCompile(`^[A-Za-z0-9_.:-]{1,64}$`).MatchString(result.EdgeID) ||
		result.RuntimePermissionsChanged == nil || *result.RuntimePermissionsChanged {
		return nil, errRotation
	}
	return &result, nil
}
