package clientrelease

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/skillmanifest"
	"strings"
)

// RetainedManifest resolves one compatible release against actual binary bytes.
// No directory names or local records confer release trust.
func RetainedManifest(directory, digest, binary string) (string, error) {
	key, err := skillmanifest.ParsePublicKey(skillmanifest.ReleasePublicKeyB64)
	if err != nil {
		return "", err
	}
	return retainedManifest(directory, digest, binary, runtime.GOOS, runtime.GOARCH, key)
}
func retainedManifest(directory, digest, binary, goos, arch string, key ed25519.PublicKey) (string, error) {
	actual, err := Digest(binary)
	if err != nil {
		return "", err
	}
	if actual != digest {
		return "", errors.New("client-release: historical binary mismatch")
	}
	root := filepath.Join(directory, "client-releases")
	dir := filepath.Join(root, digest)
	for _, path := range []string{root, dir} {
		info, err := os.Lstat(path)
		if err != nil {
			return "", errors.New("未找到本机发行清单，请提供 --manifest FILE")
		}
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || (runtime.GOOS != "windows" && info.Mode().Perm() != 0700) {
			return "", errors.New("client-release: unsafe retained directory")
		}
	}
	f, err := os.Open(dir)
	if err != nil {
		return "", err
	}
	entries, readErr := f.ReadDir(33)
	f.Close()
	if readErr != nil && readErr != io.EOF {
		return "", readErr
	}
	if len(entries) > 32 {
		return "", errors.New("client-release: retained directory budget exceeded")
	}
	selected := ""
	count := 0
	for _, entry := range entries {
		name := entry.Name()
		if !strings.HasPrefix(name, "manifest-") || !strings.HasSuffix(name, ".json") {
			continue
		}
		count++
		if count > 8 {
			return "", errors.New("client-release: manifest budget exceeded; provide --manifest FILE")
		}
		expected := strings.TrimSuffix(strings.TrimPrefix(name, "manifest-"), ".json")
		rawDigest, err := hex.DecodeString(expected)
		if err != nil || len(rawDigest) != 32 || hex.EncodeToString(rawDigest) != expected {
			return "", errors.New("client-release: invalid retained manifest name")
		}
		path := filepath.Join(dir, name)
		mf, err := openRegular(path, 1<<20)
		if err != nil {
			return "", err
		}
		raw, err := io.ReadAll(io.LimitReader(mf, (1<<20)+1))
		mf.Close()
		if err != nil || len(raw) > 1<<20 {
			return "", errors.New("client-release: invalid retained manifest size")
		}
		hash := sha256.Sum256(raw)
		if hex.EncodeToString(hash[:]) != expected {
			return "", errors.New("client-release: retained manifest drift")
		}
		if _, err := checkUpgrade(path, binary, goos, arch, key); err != nil {
			continue
		}
		if selected != "" {
			return "", errors.New("多个清单匹配历史程序，请显式提供 --manifest FILE")
		}
		selected = path
	}
	if selected == "" {
		return "", errors.New("未找到兼容的本机发行清单，请提供 --manifest FILE")
	}
	return selected, nil
}
