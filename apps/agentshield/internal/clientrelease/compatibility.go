package clientrelease

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/skillmanifest"
)

// CheckUpgrade verifies the signed declaration and candidate bytes, without
// executing a binary or approving a state transition.
func CheckUpgrade(manifestPath, binaryPath string) (string, error) {
	key, err := skillmanifest.ParsePublicKey(skillmanifest.ReleasePublicKeyB64)
	if err != nil {
		return "", err
	}
	return checkUpgrade(manifestPath, binaryPath, runtime.GOOS, runtime.GOARCH, key)
}
func checkUpgrade(manifestPath, binaryPath, goos, arch string, key ed25519.PublicKey) (string, error) {
	f, err := openRegular(manifestPath, 1<<20)
	if err != nil {
		return "", err
	}
	raw, err := io.ReadAll(io.LimitReader(f, (1<<20)+1))
	f.Close()
	if err != nil || len(raw) > 1<<20 {
		return "", errors.New("client-upgrade-check: invalid manifest size")
	}
	var m skillmanifest.Manifest
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if dec.Decode(&m) != nil || dec.Decode(new(any)) != io.EOF {
		return "", errors.New("client-upgrade-check: invalid manifest")
	}
	if err = skillmanifest.VerifyWithPublicKey(&m, key); err != nil {
		return "", err
	}
	if err = skillmanifest.CheckClientCompatibility(&m); err != nil {
		return "", err
	}
	if m.Binary.Name != "siq-agent-security" || m.Binary.Version == "" {
		return "", errors.New("client-upgrade-check: invalid product")
	}
	count := 0
	var pin skillmanifest.Artifact
	for _, a := range m.Binary.Artifacts {
		if a.OS == goos && a.Arch == arch {
			count++
			pin = a
		}
	}
	digest, err := hex.DecodeString(pin.SHA256)
	if count != 1 || err != nil || len(digest) != 32 || hex.EncodeToString(digest) != pin.SHA256 || pin.Bytes < 1 || pin.Bytes > maxBinaryBytes {
		return "", errors.New("client-upgrade-check: invalid target pin")
	}
	binary, err := openRegular(binaryPath, pin.Bytes)
	if err != nil {
		return "", err
	}
	defer binary.Close()
	hash := sha256.New()
	n, err := io.Copy(hash, io.LimitReader(binary, pin.Bytes+1))
	if err != nil || n != pin.Bytes || !bytes.Equal(hash.Sum(nil), digest) {
		return "", errors.New("client-upgrade-check: candidate integrity mismatch")
	}
	return m.Binary.Version, nil
}
