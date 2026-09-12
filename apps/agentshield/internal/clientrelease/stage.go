// Package clientrelease stages verified binaries without executing or activating them.
package clientrelease

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/skillmanifest"
	"siq-agent-security/apps/agentshield/internal/state"
)

const maxBinaryBytes int64 = 128 << 20

func openRegular(path string, limit int64) (*os.File, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > limit {
		return nil, errors.New("client-stage: ordinary bounded file required")
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	actual, err := f.Stat()
	if err != nil || !os.SameFile(info, actual) {
		f.Close()
		return nil, errors.New("client-stage: source changed")
	}
	return f, nil
}

func Stage(directory, manifestPath, binaryPath string) (string, error) {
	trusted, err := skillmanifest.ParsePublicKey(skillmanifest.ReleasePublicKeyB64)
	if err != nil {
		return "", err
	}
	return stage(directory, manifestPath, binaryPath, runtime.GOOS, runtime.GOARCH, trusted)
}

// The custom trust anchor is package-private and only used by test fixtures.
func stage(directory, manifestPath, binaryPath, goos, arch string, trusted ed25519.PublicKey) (result string, resultErr error) {
	manifestFile, err := openRegular(manifestPath, 1<<20)
	if err != nil {
		return "", err
	}
	raw, err := io.ReadAll(io.LimitReader(manifestFile, (1<<20)+1))
	manifestFile.Close()
	if err != nil || len(raw) > 1<<20 {
		return "", errors.New("client-stage: invalid manifest size")
	}
	var m skillmanifest.Manifest
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if dec.Decode(&m) != nil || dec.Decode(new(any)) != io.EOF {
		return "", errors.New("client-stage: invalid manifest")
	}
	if err = skillmanifest.VerifyWithPublicKey(&m, trusted); err != nil {
		return "", err
	}
	if (m.ManifestVersion != 1 && m.ManifestVersion != 2) || m.Binary.Name != "siq-agent-security" || m.Binary.Version == "" {
		return "", errors.New("client-stage: incompatible manifest identity")
	}
	var pin skillmanifest.Artifact
	count := 0
	for _, a := range m.Binary.Artifacts {
		if a.OS == goos && a.Arch == arch {
			pin = a
			count++
		}
	}
	digest, err := hex.DecodeString(pin.SHA256)
	if count != 1 || err != nil || len(digest) != sha256.Size || hex.EncodeToString(digest) != pin.SHA256 || pin.Bytes < 1 || pin.Bytes > maxBinaryBytes {
		return "", errors.New("client-stage: invalid or ambiguous target artifact")
	}
	source, err := openRegular(binaryPath, pin.Bytes)
	if err != nil {
		return "", err
	}
	defer source.Close()
	if directory == "" {
		return "", errors.New("client-stage: state directory required")
	}
	root := filepath.Join(directory, "client-releases")
	// Refuse a pre-existing symlink at either managed publication directory.
	if err = privateDirectory(root); err != nil {
		return "", err
	}
	w, err := state.AcquireWriter(root)
	if err != nil {
		return "", err
	}
	defer func() { resultErr = errors.Join(resultErr, w.Release()) }()
	versionDir := filepath.Join(root, pin.SHA256)
	if err = privateDirectory(versionDir); err != nil {
		return "", err
	}
	temp, err := os.CreateTemp(versionDir, ".candidate-*")
	if err != nil {
		return "", err
	}
	defer os.Remove(temp.Name())
	defer temp.Close()
	hash := sha256.New()
	n, err := io.Copy(io.MultiWriter(temp, hash), io.LimitReader(source, pin.Bytes+1))
	if err != nil || n != pin.Bytes || !bytes.Equal(hash.Sum(nil), digest) {
		return "", errors.New("client-stage: candidate size or digest mismatch")
	}
	if err = temp.Chmod(0700); err != nil {
		return "", err
	}
	if err = temp.Sync(); err != nil {
		return "", err
	}
	if err = temp.Close(); err != nil {
		return "", err
	}
	name := "siq-agent-security"
	if goos == "windows" {
		name += ".exe"
	}
	result = filepath.Join(versionDir, name)
	if err = publish(temp.Name(), result, pin.Bytes, pin.SHA256, 0700); err != nil {
		return "", err
	}
	manifestHash := sha256.Sum256(raw)
	manifestDigest := hex.EncodeToString(manifestHash[:])
	mf, err := os.CreateTemp(versionDir, ".manifest-*")
	if err != nil {
		return "", err
	}
	defer os.Remove(mf.Name())
	defer mf.Close()
	if _, err = mf.Write(raw); err != nil {
		return "", err
	}
	if err = mf.Sync(); err != nil {
		return "", err
	}
	if err = mf.Close(); err != nil {
		return "", err
	}
	if err = publish(mf.Name(), filepath.Join(versionDir, "manifest-"+manifestDigest+".json"), int64(len(raw)), manifestDigest, 0600); err != nil {
		return "", err
	}
	return result, nil
}

func privateDirectory(path string) error {
	if err := os.MkdirAll(path, 0700); err != nil {
		return err
	}
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || (runtime.GOOS != "windows" && info.Mode().Perm() != 0700) {
		return errors.New("client-stage: managed directory is not an ordinary directory")
	}
	return nil
}

func publish(temp, target string, size int64, digest string, mode os.FileMode) error {
	if err := os.Link(temp, target); err != nil {
		if !errors.Is(err, os.ErrExist) {
			return err
		}
		f, err := openRegular(target, size)
		if err != nil {
			return err
		}
		defer f.Close()
		info, err := f.Stat()
		if err != nil {
			return err
		}
		if runtime.GOOS != "windows" && info.Mode().Perm() != mode {
			return errors.New("client-stage: existing artifact permissions changed")
		}
		hash := sha256.New()
		n, err := io.Copy(hash, io.LimitReader(f, size+1))
		if err != nil || n != size || hex.EncodeToString(hash.Sum(nil)) != digest {
			return errors.New("client-stage: existing artifact drift; refusing overwrite")
		}
	}
	if runtime.GOOS != "windows" {
		d, err := os.Open(filepath.Dir(target))
		if err != nil {
			return err
		}
		defer d.Close()
		return d.Sync()
	}
	return nil
}
