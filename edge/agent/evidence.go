package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

// The redactor (protocol.NewRedactor, siq.redaction.v1), content hashing
// (protocol.ContentHash) and the .env refusal rule live in the shared protocol
// package so the connectors and the Edge use the same implementation.

// Signer owns the Edge Ed25519 device key used for evidence and batch signing.
// Security invariant: private keys never leave the device.
type Signer struct {
	priv ed25519.PrivateKey
	pub  ed25519.PublicKey
}

// NewSigner generates a fresh Ed25519 keypair.
func NewSigner() (*Signer, error) {
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return nil, fmt.Errorf("signer: keygen: %w", err)
	}
	return &Signer{priv: priv, pub: pub}, nil
}

// NewSignerFromSeed restores the signer from a base64 32-byte seed (state.json).
// Evidence signatures become stable across restarts so the control plane can
// re-verify them.
func NewSignerFromSeed(seedB64 string) (*Signer, error) {
	seed, err := base64.StdEncoding.DecodeString(seedB64)
	if err != nil || len(seed) != ed25519.SeedSize {
		return nil, fmt.Errorf("signer: invalid seed: %w", err)
	}
	priv := ed25519.NewKeyFromSeed(seed)
	pub := priv.Public().(ed25519.PublicKey)
	return &Signer{priv: priv, pub: pub}, nil
}

// SeedB64 exports the private key seed (base64) for persistence in state.json.
// The state file is 0600; the seed never leaves the device.
func (s *Signer) SeedB64() string {
	return base64.StdEncoding.EncodeToString(s.priv.Seed())
}

// PublicKeyPEM returns the public key in PKIX PEM form (sent to the control
// plane at register time).
func (s *Signer) PublicKeyPEM() (string, error) {
	der, err := x509.MarshalPKIXPublicKey(s.pub)
	if err != nil {
		return "", fmt.Errorf("signer: marshal public key: %w", err)
	}
	return string(pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der})), nil
}

// Sign signs data and returns the hex-encoded Ed25519 signature.
func (s *Signer) Sign(data []byte) (string, error) {
	return hex.EncodeToString(ed25519.Sign(s.priv, data)), nil
}

// VerifySignature checks sigHex against data with the given PEM public key.
func VerifySignature(pubPEM string, data []byte, sigHex string) error {
	block, _ := pem.Decode([]byte(pubPEM))
	if block == nil {
		return errors.New("verify: invalid PEM public key")
	}
	pubAny, err := x509.ParsePKIXPublicKey(block.Bytes)
	if err != nil {
		return fmt.Errorf("verify: parse public key: %w", err)
	}
	pub, ok := pubAny.(ed25519.PublicKey)
	if !ok {
		return errors.New("verify: public key is not Ed25519")
	}
	sig, err := hex.DecodeString(sigHex)
	if err != nil {
		return fmt.Errorf("verify: decode signature: %w", err)
	}
	if !ed25519.Verify(pub, data, sig) {
		return errors.New("verify: signature mismatch")
	}
	return nil
}

// SealEvidence fills the Edge-owned evidence fields (contract §5: the Edge
// fills signature and collected_at at packaging time) and signs the canonical
// JSON of the evidence (signature excluded from the signed payload).
func SealEvidence(ev *protocol.Evidence, signer *Signer, collectorID string) error {
	now := time.Now().UTC().Format(time.RFC3339)
	if ev.CollectedAt == "" {
		ev.CollectedAt = now
	}
	// Edge owns the identity boundary. Connector-provided tenant/environment/
	// collector values are never trusted or signed through.
	ev.TenantID = ""
	ev.EnvironmentID = ""
	ev.CollectorID = collectorID
	if ev.RedactionProfile == "" {
		ev.RedactionProfile = protocol.RedactionProfile
	}
	if ev.ObservedAt == "" {
		ev.ObservedAt = now
	}
	clone := *ev
	clone.Signature = ""
	data, err := CanonicalJSON(&clone)
	if err != nil {
		return fmt.Errorf("seal: encode evidence %s: %w", ev.EvidenceID, err)
	}
	sig, err := signer.Sign(data)
	if err != nil {
		return fmt.Errorf("seal: sign evidence %s: %w", ev.EvidenceID, err)
	}
	ev.Signature = sig
	return nil
}

// CanonicalJSON is shared by evidence and batch signatures. encoding/json
// sorts map keys; SetEscapeHTML(false) aligns with the control plane's UTF-8
// canonical form. The encoder newline is removed before signing.
func CanonicalJSON(value any) ([]byte, error) {
	raw, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	var normalized any
	if err := json.Unmarshal(raw, &normalized); err != nil {
		return nil, err
	}
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(normalized); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(buf.Bytes(), []byte("\n")), nil
}

// ValidateBatchReferences enforces contract hard requirement 4: every
// evidence in a batch must be referenced by at least one candidate's
// evidence_ids, otherwise it is dropped. It also enforces the schema's
// minItems:1 on candidate.evidence_ids.
func ValidateBatchReferences(cands []*protocol.Candidate, evs []*protocol.Evidence) (kept, dropped []*protocol.Evidence, err error) {
	for _, c := range cands {
		if len(c.EvidenceIDs) == 0 {
			return nil, nil, fmt.Errorf("candidate %q has empty evidence_ids (candidate.schema.json requires minItems:1)", c.CandidateID)
		}
	}
	referenced := make(map[string]struct{}, len(evs))
	for _, c := range cands {
		for _, id := range c.EvidenceIDs {
			referenced[id] = struct{}{}
		}
	}
	kept = make([]*protocol.Evidence, 0, len(evs))
	dropped = make([]*protocol.Evidence, 0)
	for _, ev := range evs {
		if _, ok := referenced[ev.EvidenceID]; ok {
			kept = append(kept, ev)
		} else {
			dropped = append(dropped, ev)
		}
	}
	return kept, dropped, nil
}
