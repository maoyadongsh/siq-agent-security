package installplan

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/canon"
)

func releaseFixture(t *testing.T) (Release, ed25519.PublicKey, ed25519.PrivateKey) {
	t.Helper()
	pub, key, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	r := Release{
		SchemaVersion: "enterprise-release/v1", Product: "siq-agent-security-enterprise",
		Version: "0.4.0-test", SourceCommit: strings.Repeat("a", 40),
		SignedBy: base64.StdEncoding.EncodeToString(pub),
		Artifacts: []Artifact{
			{ID: "edge-agent", OS: "linux", Arch: "arm64", Path: "bin/arm64/edge-agent", SHA256: strings.Repeat("a", 64), Bytes: 123},
			{ID: "hermes", OS: "linux", Arch: "arm64", Path: "bin/arm64/hermes-connector", SHA256: strings.Repeat("b", 64), Bytes: 456},
		},
	}
	return r, pub, key
}

func signFixture(t *testing.T, r Release, key ed25519.PrivateKey) []byte {
	t.Helper()
	raw, err := json.Marshal(r)
	if err != nil {
		t.Fatal(err)
	}
	v, err := canon.Decode(raw)
	if err != nil {
		t.Fatal(err)
	}
	m := v.(map[string]any)
	delete(m, "signature")
	payload, err := canon.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	r.Signature = hex.EncodeToString(ed25519.Sign(key, payload))
	raw, err = json.Marshal(r)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func TestReleaseSignatureAndPinnedPublisher(t *testing.T) {
	r, pub, key := releaseFixture(t)
	raw := signFixture(t, r, key)
	if _, err := verifyRelease(raw, pub); err != nil {
		t.Fatal(err)
	}
	if _, err := VerifyRelease(raw); err != ErrInvalid {
		t.Fatal("test publisher trusted by production verifier")
	}
	if _, err := VerifyPlanRelease(Plan{}, raw); err != ErrInvalid {
		t.Fatal("test publisher trusted for installation")
	}
	tampered := strings.Replace(string(raw), `"bytes":123`, `"bytes":124`, 1)
	if _, err := verifyRelease([]byte(tampered), pub); err != ErrInvalid {
		t.Fatal("tampered release accepted")
	}
	for _, path := range []string{
		"../../../apps/agentshield/internal/skillmanifest/manifest.go",
	} {
		body, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(string(body), ReleasePublicKeyB64) {
			t.Fatalf("publisher differs from %s", path)
		}
	}
}

func TestReleaseRejectsMalformedWire(t *testing.T) {
	r, pub, key := releaseFixture(t)
	raw := string(signFixture(t, r, key))
	for i, input := range []string{
		raw + `{}`, `null`, `[]`, `{`,
		strings.Replace(raw, `"bytes":123`, `"bytes":123,"bytes":123`, 1),
		strings.Replace(raw, `"bytes":123`, `"bytes":123.0`, 1),
		strings.Replace(raw, `"bytes":123`, `"bytes":1e2`, 1),
		strings.Replace(raw, `"bytes":123`, `"bytes":null`, 1),
		strings.Replace(raw, `"bytes":123`, `"Bytes":123`, 1),
		strings.Replace(raw, `"bytes":123`, `"bytes":9223372036854775808`, 1),
		strings.Replace(raw, `"bytes":123`, `"bytes":123,"unexpected":true`, 1),
		strings.Replace(raw, `,"bytes":123`, ``, 1),
		strings.Repeat(" ", MaxBytes+1), raw + string([]byte{0xff}),
	} {
		if _, err := verifyRelease([]byte(input), pub); err != ErrInvalid {
			t.Fatalf("case %d accepted", i)
		}
	}
}

func TestReleaseRejectsSignedInvalidFields(t *testing.T) {
	for name, mutate := range map[string]func(*Release){
		"schema":       func(r *Release) { r.SchemaVersion = "other" },
		"product":      func(r *Release) { r.Product = "other" },
		"version":      func(r *Release) { r.Version = "../other" },
		"commit":       func(r *Release) { r.SourceCommit = "main" },
		"publisher":    func(r *Release) { r.SignedBy = "other" },
		"traversal":    func(r *Release) { r.Artifacts[0].Path = "../../edge-agent" },
		"os":           func(r *Release) { r.Artifacts[0].OS = "darwin" },
		"arch":         func(r *Release) { r.Artifacts[0].Arch = "other" },
		"missing_edge": func(r *Release) { r.Artifacts[0].Arch = "amd64"; r.Artifacts[0].Path = "bin/amd64/edge-agent" },
		"digest":       func(r *Release) { r.Artifacts[0].SHA256 = "invalid" },
		"empty":        func(r *Release) { r.Artifacts = nil },
		"zero_size":    func(r *Release) { r.Artifacts[0].Bytes = 0 },
		"oversize":     func(r *Release) { r.Artifacts[0].Bytes = (256 << 20) + 1 },
		"duplicate":    func(r *Release) { r.Artifacts = append(r.Artifacts, r.Artifacts[0]) },
		"unknown_connector": func(r *Release) {
			r.Artifacts[1].ID = "arbitrary"
			r.Artifacts[1].Path = "bin/arm64/arbitrary-connector"
		},
	} {
		t.Run(name, func(t *testing.T) {
			r, pub, key := releaseFixture(t)
			mutate(&r)
			if _, err := verifyRelease(signFixture(t, r, key), pub); err != ErrInvalid {
				t.Fatal("signed invalid manifest accepted")
			}
		})
	}
}

func TestReleasePlanBinding(t *testing.T) {
	r, pub, key := releaseFixture(t)
	raw := signFixture(t, r, key)
	verified, err := verifyRelease(raw, pub)
	if err != nil {
		t.Fatal(err)
	}
	p, err := Parse(fixture(t))
	if err != nil {
		t.Fatal(err)
	}
	hash := sha256.Sum256(raw)
	p.ReleaseManifestSHA256 = hex.EncodeToString(hash[:])
	if err := bindRelease(*p, raw, verified); err != nil {
		t.Fatal(err)
	}
	for name, mutate := range map[string]func(*Plan){
		"manifest":          func(p *Plan) { p.ReleaseManifestSHA256 = strings.Repeat("0", 64) },
		"version":           func(p *Plan) { p.ReleaseVersion = "0.4.1" },
		"arch":              func(p *Plan) { p.TargetArch = "amd64" },
		"connector_digest":  func(p *Plan) { p.Connectors[0].ArtifactSHA256 = strings.Repeat("0", 64) },
		"connector_version": func(p *Plan) { p.Connectors[0].Version = "0.4.1" },
		"connector_missing": func(p *Plan) { p.Connectors[0].ID = "openclaw" },
		"purpose":           func(p *Plan) { p.Purpose = "enforce" },
	} {
		t.Run(name, func(t *testing.T) {
			copyPlan := *p
			copyPlan.Connectors = append([]Connector(nil), p.Connectors...)
			mutate(&copyPlan)
			if bindRelease(copyPlan, raw, verified) != ErrInvalid {
				t.Fatal("mismatch accepted")
			}
		})
	}
}
