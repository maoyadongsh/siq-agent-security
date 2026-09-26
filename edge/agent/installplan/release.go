package installplan

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"io"
	"reflect"
	"regexp"
	"unicode/utf8"

	"siq-agent-security/edge/agent/canon"
)

// Same publisher as historical Skill releases; never read a key from the bundle.
const ReleasePublicKeyB64 = "LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY="

type Artifact struct {
	ID     string `json:"id"`
	OS     string `json:"os"`
	Arch   string `json:"arch"`
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
	Bytes  int64  `json:"bytes"`
}
type Release struct {
	SchemaVersion string     `json:"schema_version"`
	Product       string     `json:"product"`
	Version       string     `json:"version"`
	SourceCommit  string     `json:"source_commit"`
	Artifacts     []Artifact `json:"artifacts"`
	SignedBy      string     `json:"signed_by"`
	Signature     string     `json:"signature"`
}

// VerifyRelease uses only the compiled publisher identity. Test key injection is
// private to this package, not a CLI/environment escape hatch.
func VerifyRelease(raw []byte) (*Release, error) {
	pub, _ := base64.StdEncoding.DecodeString(ReleasePublicKeyB64)
	return verifyRelease(raw, ed25519.PublicKey(pub))
}

func verifyRelease(raw []byte, key ed25519.PublicKey) (*Release, error) {
	if len(raw) > MaxBytes || !utf8.Valid(raw) || len(key) != ed25519.PublicKeySize {
		return nil, ErrInvalid
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	v, err := readValue(d, 0)
	if err != nil || !exactShape(v, reflect.TypeOf(Release{})) {
		return nil, ErrInvalid
	}
	if _, err := d.Token(); err != io.EOF {
		return nil, ErrInvalid
	}
	var release Release
	if json.Unmarshal(raw, &release) != nil || release.validate() != nil || release.SignedBy != base64.StdEncoding.EncodeToString(key) {
		return nil, ErrInvalid
	}
	sig, err := hex.DecodeString(release.Signature)
	if err != nil || len(sig) != ed25519.SignatureSize {
		return nil, ErrInvalid
	}
	object := v.(map[string]any)
	delete(object, "signature")
	payload, err := canon.Marshal(object)
	if err != nil || !ed25519.Verify(key, payload, sig) {
		return nil, ErrInvalid
	}
	return &release, nil
}

func (r Release) validate() error {
	if r.SchemaVersion != "enterprise-release/v1" || r.Product != "siq-agent-security-enterprise" || !version.MatchString(r.Version) || !regexp.MustCompile(`^[a-f0-9]{40}$`).MatchString(r.SourceCommit) || !regexp.MustCompile(`^[a-f0-9]{128}$`).MatchString(r.Signature) || len(r.Artifacts) < 2 || len(r.Artifacts) > 26 {
		return ErrInvalid
	}
	seen := map[string]bool{}
	edges := map[string]bool{}
	connectors := map[string]int{}
	for _, a := range r.Artifacts {
		if a.OS != "linux" || !oneOf(a.Arch, "arm64", "amd64") || !digest.MatchString(a.SHA256) || a.Bytes < 1 || a.Bytes > 256<<20 {
			return ErrInvalid
		}
		name := a.ID + "-connector"
		if a.ID == "edge-agent" {
			name = a.ID
			edges[a.Arch] = true
		} else {
			if !oneOf(a.ID, "hermes", "openclaw", "directory", "docker", "process", "systemd", "kubernetes", "mcp", "piagent", "workbuddy", "dify", "siq") {
				return ErrInvalid
			}
			connectors[a.Arch]++
		}
		if a.Path != "bin/"+a.Arch+"/"+name || seen[a.Path] {
			return ErrInvalid
		}
		seen[a.Path] = true
	}
	for arch := range edges {
		if connectors[arch] == 0 {
			return ErrInvalid
		}
	}
	for arch := range connectors {
		if !edges[arch] {
			return ErrInvalid
		}
	}
	return nil
}

// VerifyPlanRelease re-verifies the signature and binds pins; it intentionally
// does not treat an operator-provided plan digest as a substitute for signature.
func VerifyPlanRelease(plan Plan, raw []byte) (*Release, error) {
	r, err := VerifyRelease(raw)
	if err != nil {
		return nil, err
	}
	if err := bindRelease(plan, raw, r); err != nil {
		return nil, err
	}
	return r, nil
}

func bindRelease(p Plan, raw []byte, r *Release) error {
	if p.Validate() != nil {
		return ErrInvalid
	}
	hash := sha256.Sum256(raw)
	if p.ReleaseManifestSHA256 != hex.EncodeToString(hash[:]) || p.ReleaseVersion != r.Version {
		return ErrInvalid
	}
	available := map[string]Artifact{}
	for _, a := range r.Artifacts {
		if a.Arch == p.TargetArch {
			available[a.ID] = a
		}
	}
	if _, ok := available["edge-agent"]; !ok {
		return ErrInvalid
	}
	for _, c := range p.Connectors {
		a, ok := available[c.ID]
		if !ok || a.SHA256 != c.ArtifactSHA256 || c.Version != r.Version || c.ProtocolVersion != "connector-protocol.v1" {
			return ErrInvalid
		}
	}
	return nil
}
