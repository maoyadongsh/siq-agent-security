// Package signing holds the local-mode Ed25519 identity of the agentshield
// binary (ADR-011 D3). It signs admission / grant / receipt documents over
// their canonical JSON bytes (canon.Marshal) so that the Python control plane
// can verify them with the same public key, and vice versa.
//
// Key material lives only in the state directory (0600); platform adapters and
// the model never receive it. There is no fcntl: cross-platform exclusivity is
// obtained with O_EXCL on first creation.
package signing

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"siq-agent-security/apps/agentshield/internal/canon"
)

// SeedEnv lets deployments pin a base64 32-byte seed (mirrors
// SIQ_AS_TASK_SIGNING_KEY_SEED semantics on the Python side).
const SeedEnv = "AGENTSHIELD_SIGNING_KEY_SEED"

// Key is a loaded signing identity.
type Key struct {
	priv ed25519.PrivateKey
	pub  ed25519.PublicKey
}

// FromSeed builds a key from a raw 32-byte seed.
func FromSeed(seed []byte) (*Key, error) {
	if len(seed) != ed25519.SeedSize {
		return nil, fmt.Errorf("signing: seed must be %d bytes", ed25519.SeedSize)
	}
	priv := ed25519.NewKeyFromSeed(seed)
	return &Key{priv: priv, pub: priv.Public().(ed25519.PublicKey)}, nil
}

// Load returns the key from SeedEnv if set, otherwise from <stateDir>/keys/signing.seed,
// generating it on first use. Generation is atomic (O_EXCL) so two concurrent
// first runs cannot end up with different keys.
func Load(stateDir string) (*Key, error) {
	if b64 := strings.TrimSpace(os.Getenv(SeedEnv)); b64 != "" {
		seed, err := base64.StdEncoding.Strict().DecodeString(b64)
		if err != nil {
			return nil, fmt.Errorf("signing: %s is not valid base64", SeedEnv)
		}
		return FromSeed(seed)
	}
	if stateDir == "" {
		return nil, errors.New("signing: state directory required (fail closed)")
	}
	dir := filepath.Join(stateDir, "keys")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	path := filepath.Join(dir, "signing.seed")
	if raw, err := os.ReadFile(path); err == nil {
		return decodeSeedFile(path, raw)
	}
	seed := make([]byte, ed25519.SeedSize)
	if _, err := rand.Read(seed); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		if errors.Is(err, os.ErrExist) {
			raw, rerr := os.ReadFile(path)
			if rerr != nil {
				return nil, rerr
			}
			return decodeSeedFile(path, raw)
		}
		return nil, err
	}
	if _, err := f.WriteString(base64.StdEncoding.EncodeToString(seed)); err != nil {
		_ = f.Close()
		return nil, err
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		return nil, err
	}
	if err := f.Close(); err != nil {
		return nil, err
	}
	return FromSeed(seed)
}

func decodeSeedFile(path string, raw []byte) (*Key, error) {
	seed, err := base64.StdEncoding.Strict().DecodeString(strings.TrimSpace(string(raw)))
	if err != nil {
		return nil, fmt.Errorf("signing: seed file %s is not valid base64", filepath.Base(path))
	}
	k, err := FromSeed(seed)
	if err != nil {
		return nil, fmt.Errorf("signing: seed file %s has invalid length", filepath.Base(path))
	}
	return k, nil
}

// Public returns the verification key.
func (k *Key) Public() ed25519.PublicKey { return k.pub }

// PublicBase64 matches public_key_base64() on the Python side.
func (k *Key) PublicBase64() string { return base64.StdEncoding.EncodeToString(k.pub) }

// SignCanonical signs canon.Marshal(doc) and returns the 128-hex signature used
// by the admission / grant / receipt schemas. Callers pass the document
// WITHOUT its signature field.
func (k *Key) SignCanonical(doc map[string]any) (string, error) {
	msg, err := canon.Marshal(doc)
	if err != nil {
		return "", err
	}
	return hex.EncodeToString(ed25519.Sign(k.priv, msg)), nil
}

// VerifyCanonical checks a 128-hex signature over canon.Marshal(doc).
func VerifyCanonical(pub ed25519.PublicKey, doc map[string]any, sigHex string) bool {
	sig, err := hex.DecodeString(sigHex)
	if err != nil || len(sig) != ed25519.SignatureSize || len(pub) != ed25519.PublicKeySize {
		return false
	}
	msg, err := canon.Marshal(doc)
	if err != nil {
		return false
	}
	return ed25519.Verify(pub, msg, sig)
}

// SignBytes / VerifyBytes are for hash-chain receipts, where the signature is
// over the hex hash string itself.
func (k *Key) SignBytes(msg []byte) string { return hex.EncodeToString(ed25519.Sign(k.priv, msg)) }

// VerifyBytes checks a 128-hex signature over msg.
func VerifyBytes(pub ed25519.PublicKey, msg []byte, sigHex string) bool {
	sig, err := hex.DecodeString(sigHex)
	if err != nil || len(sig) != ed25519.SignatureSize || len(pub) != ed25519.PublicKeySize {
		return false
	}
	return ed25519.Verify(pub, msg, sig)
}
