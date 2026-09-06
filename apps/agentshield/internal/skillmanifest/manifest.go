// Package skillmanifest builds and verifies the signed skill-manifest.json
// published next to skills/siq-agent-security/SKILL.md (dev-spec §5.2, schema
// skill-manifest.v1).
//
// The v1 trust root is a repo-local Ed25519 key. The public key is embedded in
// bootstrap.sh / bootstrap.ps1 and in ReleasePublicKeyB64; the private seed is
// SIQ_AGENT_SECURITY_RELEASE_SEED (legacy AGENTSHIELD_RELEASE_SEED still works)
// and is never committed.
package skillmanifest

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
)

// ReleasePublicKeyB64 is the v1 local trust root (Ed25519, standard base64).
// Bootstrap scripts must embed the same value. Rotating it requires re-signing
// skill-manifest.json and updating both bootstrap files.
const ReleasePublicKeyB64 = "LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY="

// SeedEnv is the 32-byte Ed25519 seed (standard base64) used to sign a release.
const SeedEnv = product.EnvReleaseSeed

// DefaultVersion is the Skill and binary version for this snapshot.
const DefaultVersion = "0.2.0"

// DefaultURLBase is the intended GitHub Release prefix. Download is opt-in
// (SIQ_AGENT_SECURITY_ALLOW_DOWNLOAD=1) after signed-manifest verify; hashes
// always pin the object (DEV04-E).
const DefaultURLBase = "https://github.com/maoyadongsh/siq-agent-security/releases/download/siq-agent-security-v0.2.0"

// SkillDescription is copied from SKILL.md frontmatter (≤60 chars, period).
const SkillDescription = "Admits unknown skills and signs each tool-call receipt."

// Targets is the cross-compile matrix required by spec §5.2.
var Targets = []struct {
	OS   string
	Arch string
	Ext  string
}{
	{"linux", "amd64", ""},
	{"linux", "arm64", ""},
	{"darwin", "arm64", ""},
	{"windows", "amd64", ".exe"},
}

// Artifact is one binary pin.
type Artifact struct {
	OS     string `json:"os"`
	Arch   string `json:"arch"`
	SHA256 string `json:"sha256"`
	URL    string `json:"url"`
	Bytes  int64  `json:"bytes"`
}

// Skill is the skill identity block.
type Skill struct {
	Name        string   `json:"name"`
	Version     string   `json:"version"`
	Description string   `json:"description"`
	ContentHash string   `json:"content_hash"`
	SubSkills   []string `json:"sub_skills,omitempty"`
}

// Binary is the binary identity block.
type Binary struct {
	Name      string     `json:"name"`
	Version   string     `json:"version"`
	Artifacts []Artifact `json:"artifacts"`
}

// Rulepack is the embedded-pack pin plus the key that would verify an external pack.
type Rulepack struct {
	Version      int    `json:"version"`
	SHA256       string `json:"sha256"`
	PublicKeyB64 string `json:"public_key_b64"`
}

// Row is one platform × OS support-matrix entry.
type Row struct {
	Platform string   `json:"platform"`
	OS       string   `json:"os"`
	Tiers    []string `json:"tiers"`
	Status   string   `json:"status"`
	Requires []string `json:"requires,omitempty"`
	Note     string   `json:"note,omitempty"`
}

// Manifest is the signed document. Signature covers canon.Marshal of the
// document with the signature field omitted.
type Manifest struct {
	ManifestVersion int      `json:"manifest_version"`
	Skill           Skill    `json:"skill"`
	Binary          Binary   `json:"binary"`
	Rulepack        Rulepack `json:"rulepack"`
	SupportMatrix   []Row    `json:"support_matrix"`
	SignedBy        string   `json:"signed_by"`
	Signature       string   `json:"signature"`
}

// Options for Build.
type Options struct {
	Version     string
	Description string
	ContentHash string
	Artifacts   []Artifact
	Matrix      []Row
	SignedBy    string
}

// Build constructs an unsigned manifest. Signature is left empty.
func Build(opts Options) (*Manifest, error) {
	if opts.Version == "" {
		opts.Version = DefaultVersion
	}
	if opts.Description == "" {
		opts.Description = SkillDescription
	}
	if opts.ContentHash == "" || len(opts.ContentHash) != 64 {
		return nil, fmt.Errorf("skillmanifest: content_hash must be 64 hex chars")
	}
	if len(opts.Artifacts) < 1 {
		return nil, fmt.Errorf("skillmanifest: at least one binary artifact is required")
	}
	if opts.SignedBy == "" {
		opts.SignedBy = ReleasePublicKeyB64
	}
	pack, err := rulepack.Builtin()
	if err != nil {
		return nil, err
	}
	sum := sha256.Sum256(rulepack.BuiltinBytes())
	matrix := opts.Matrix
	if matrix == nil {
		matrix = DefaultMatrix()
	}
	if err := ValidateMatrix(matrix); err != nil {
		return nil, err
	}
	return &Manifest{
		ManifestVersion: 1,
		Skill: Skill{
			Name:        product.Name,
			Version:     opts.Version,
			Description: opts.Description,
			ContentHash: opts.ContentHash,
			SubSkills:   []string{"agent-asset-inventory", "skill-admission", "least-privilege-grant", "runtime-receipt"},
		},
		Binary: Binary{
			Name:      product.Name,
			Version:   opts.Version,
			Artifacts: opts.Artifacts,
		},
		Rulepack: Rulepack{
			Version:      pack.Version,
			SHA256:       hex.EncodeToString(sum[:]),
			PublicKeyB64: opts.SignedBy,
		},
		SupportMatrix: matrix,
		SignedBy:      opts.SignedBy,
	}, nil
}

// Sign fills Signature using the release key. signed_by and the rulepack
// public key are set to the key's public half before the signature is taken.
func Sign(m *Manifest, key *signing.Key) error {
	m.SignedBy = key.PublicBase64()
	m.Rulepack.PublicKeyB64 = m.SignedBy
	m.Signature = ""
	doc, err := unsignedMap(m)
	if err != nil {
		return err
	}
	sig, err := key.SignCanonical(doc)
	if err != nil {
		return err
	}
	m.Signature = sig
	return nil
}

// Verify verifies a release against the built-in trusted issuer, never a key
// supplied by the untrusted manifest itself.
func Verify(m *Manifest) error {
	pub, err := ParsePublicKey(ReleasePublicKeyB64)
	if err != nil {
		return err
	}
	return VerifyWithPublicKey(m, pub)
}

// VerifyWithPublicKey verifies against a caller-established trust anchor. It is
// used for explicit development signing self-checks; callers must not derive
// trusted from the document being verified.
func VerifyWithPublicKey(m *Manifest, trusted ed25519.PublicKey) error {
	if m == nil {
		return fmt.Errorf("skillmanifest: nil manifest")
	}
	if len(trusted) != ed25519.PublicKeySize {
		return fmt.Errorf("skillmanifest: invalid trusted public key")
	}
	if m.SignedBy != "" {
		declared, err := ParsePublicKey(m.SignedBy)
		if err != nil {
			return err
		}
		if !trusted.Equal(declared) {
			return fmt.Errorf("skillmanifest: untrusted signing identity")
		}
	}
	if m.Signature == "" {
		return fmt.Errorf("skillmanifest: missing signature")
	}
	doc, err := unsignedMap(m)
	if err != nil {
		return err
	}
	if !signing.VerifyCanonical(trusted, doc, m.Signature) {
		return fmt.Errorf("skillmanifest: signature mismatch")
	}
	return nil
}

// ParsePublicKey decodes a standard-base64 32-byte Ed25519 public key.
func ParsePublicKey(b64 string) (ed25519.PublicKey, error) {
	raw, err := base64.StdEncoding.Strict().DecodeString(strings.TrimSpace(b64))
	if err != nil {
		return nil, fmt.Errorf("skillmanifest: public key is not valid base64")
	}
	if len(raw) != ed25519.PublicKeySize {
		return nil, fmt.Errorf("skillmanifest: public key must be %d bytes", ed25519.PublicKeySize)
	}
	return ed25519.PublicKey(raw), nil
}

// KeyFromEnv loads SIQ_AGENT_SECURITY_RELEASE_SEED (or the legacy name). Fail closed if unset or invalid.
func KeyFromEnv() (*signing.Key, error) {
	b64 := product.Env(product.EnvReleaseSeed, product.EnvReleaseSeedOld)
	if b64 == "" {
		return nil, fmt.Errorf("skillmanifest: %s is not set (refusing to sign)", SeedEnv)
	}
	seed, err := base64.StdEncoding.Strict().DecodeString(b64)
	if err != nil {
		return nil, fmt.Errorf("skillmanifest: %s is not valid base64", SeedEnv)
	}
	return signing.FromSeed(seed)
}

// HashSkillDir returns content_hash of a skill directory (excludes
// skill-manifest.json, matching admission.HashDir).
func HashSkillDir(dir string) (string, error) {
	h, _, err := admission.HashDir(dir, admission.DefaultLimits)
	return h, err
}

// LoadFile reads and unmarshals a skill-manifest.json.
func LoadFile(path string) (*Manifest, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var m Manifest
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, fmt.Errorf("skillmanifest: %s: %w", filepath.Base(path), err)
	}
	return &m, nil
}

// WriteFile writes pretty-printed JSON (0600). Signature is over canonical
// bytes, not the pretty form.
func WriteFile(path string, m *Manifest) error {
	raw, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return err
	}
	raw = append(raw, '\n')
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, raw, 0o600)
}

// ArtifactName is the file name used in --bin-dir and in the unpublished URL.
func ArtifactName(osName, arch, ext string) string {
	return product.Name + "-" + osName + "-" + arch + ext
}

// HashFile returns sha256 hex and size of one built binary.
func HashFile(path string) (string, int64, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", 0, err
	}
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:]), int64(len(raw)), nil
}

func unsignedMap(m *Manifest) (map[string]any, error) {
	cp := *m
	cp.Signature = ""
	raw, err := json.Marshal(cp)
	if err != nil {
		return nil, err
	}
	v, err := canon.Decode(raw)
	if err != nil {
		return nil, err
	}
	doc, ok := v.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("skillmanifest: expected object")
	}
	delete(doc, "signature")
	return doc, nil
}
