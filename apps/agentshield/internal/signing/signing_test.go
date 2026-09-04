package signing

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
)

// Vector produced by the Python control plane (cryptography.Ed25519PrivateKey
// with seed 0x01*32 over json.dumps(sort_keys=True, separators=(",",":"))).
// Ed25519 is deterministic, so Go must reproduce the exact signature.
const (
	pyPubB64 = "iojj3XQJ8ZX9UtstPLpdcspnCb8dlBIb83SIAbQPb1w="
	pySigHex = "02731ddcc1561ddb16e65ceaf14c2f97ba6e58e7a9212bfe2fb9564f42bd6a4b836f6a521013f06b6f440f703f5f863d0b198bdbe4e3652cd7164eb41ad24f0f"
	pyDoc    = `{"b":"中文","a":[1,0.85,null],"nested":{"z":true,"y":"x"}}`
)

func pyDocMap(t *testing.T) map[string]any {
	t.Helper()
	v, err := canon.Decode([]byte(pyDoc))
	if err != nil {
		t.Fatal(err)
	}
	return v.(map[string]any)
}

func TestCrossImplementationSignature(t *testing.T) {
	k, err := FromSeed(bytes.Repeat([]byte{1}, 32))
	if err != nil {
		t.Fatal(err)
	}
	if k.PublicBase64() != pyPubB64 {
		t.Fatalf("public key mismatch: %s", k.PublicBase64())
	}
	sig, err := k.SignCanonical(pyDocMap(t))
	if err != nil {
		t.Fatal(err)
	}
	if sig != pySigHex {
		t.Fatalf("Go signature differs from Python:\n got %s\nwant %s", sig, pySigHex)
	}
	pub, _ := base64.StdEncoding.DecodeString(pyPubB64)
	if !VerifyCanonical(pub, pyDocMap(t), pySigHex) {
		t.Fatal("Python signature must verify in Go")
	}
	tampered := pyDocMap(t)
	tampered["a"] = []any{json.Number("2")}
	if VerifyCanonical(pub, tampered, pySigHex) {
		t.Fatal("tampered document must not verify")
	}
	if VerifyCanonical(pub, pyDocMap(t), "zz") || VerifyCanonical(pub[:10], pyDocMap(t), pySigHex) {
		t.Fatal("malformed signature / key must not verify")
	}
}

func TestLoadGeneratesOnceAndPersists(t *testing.T) {
	dir := t.TempDir()
	k1, err := Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	k2, err := Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	if k1.PublicBase64() != k2.PublicBase64() {
		t.Fatal("second load must reuse the persisted seed")
	}
	if runtime.GOOS != "windows" {
		info, err := os.Stat(filepath.Join(dir, "keys", "signing.seed"))
		if err != nil {
			t.Fatal(err)
		}
		if info.Mode().Perm() != 0o600 {
			t.Fatalf("seed file must be 0600, got %o", info.Mode().Perm())
		}
	}
}

func TestLoadRejectsCorruptSeed(t *testing.T) {
	dir := t.TempDir()
	_ = os.MkdirAll(filepath.Join(dir, "keys"), 0o700)
	_ = os.WriteFile(filepath.Join(dir, "keys", "signing.seed"), []byte("not base64!"), 0o600)
	if _, err := Load(dir); err == nil {
		t.Fatal("corrupt seed must fail closed, not regenerate")
	}
	_ = os.WriteFile(filepath.Join(dir, "keys", "signing.seed"), []byte(base64.StdEncoding.EncodeToString([]byte("short"))), 0o600)
	if _, err := Load(dir); err == nil {
		t.Fatal("wrong-length seed must fail closed")
	}
}

func TestLoadFromSeedEnvOverridesStateDir(t *testing.T) {
	t.Setenv(SeedEnv, base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{1}, 32)))
	k, err := Load("")
	if err != nil {
		t.Fatal(err)
	}
	if k.PublicBase64() != pyPubB64 {
		t.Fatal("seed env not honoured")
	}
	t.Setenv(SeedEnv, "@@@")
	if _, err := Load(t.TempDir()); err == nil {
		t.Fatal("invalid seed env must fail closed rather than silently generating a key")
	}
}

func TestLoadWithoutStateDirFailsClosed(t *testing.T) {
	t.Setenv(SeedEnv, "")
	if _, err := Load(""); err == nil {
		t.Fatal("no seed and no state dir must fail")
	}
}

func TestSignVerifyBytes(t *testing.T) {
	k, _ := FromSeed(bytes.Repeat([]byte{2}, 32))
	sig := k.SignBytes([]byte("abc"))
	if !VerifyBytes(k.Public(), []byte("abc"), sig) || VerifyBytes(k.Public(), []byte("abd"), sig) {
		t.Fatal("bytes signature roundtrip broken")
	}
}
