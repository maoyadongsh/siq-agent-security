package clientrelease

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/state"
)

// SnapshotCurrent preserves local observed bytes, not release authenticity.
// It never executes a candidate or promotes a snapshot into a trusted release.
func SnapshotCurrent(directory string) (string, error) {
	executable, err := os.Executable()
	if err == nil {
		executable, err = filepath.EvalSymlinks(executable)
	}
	if err != nil {
		return "", err
	}
	return snapshot(directory, executable, runtime.GOOS)
}
func snapshot(directory, sourcePath, goos string) (result string, resultErr error) {
	source, err := openRegular(sourcePath, maxBinaryBytes)
	if err != nil {
		return "", err
	}
	defer source.Close()
	if directory == "" {
		return "", errors.New("client-snapshot: state directory required")
	}
	root := filepath.Join(directory, "client-snapshots")
	if err = privateDirectory(root); err != nil {
		return "", err
	}
	w, err := state.AcquireWriter(root)
	if err != nil {
		return "", err
	}
	defer func() { resultErr = errors.Join(resultErr, w.Release()) }()
	temp, err := os.CreateTemp(root, ".source-*")
	if err != nil {
		return "", err
	}
	defer os.Remove(temp.Name())
	defer temp.Close()
	hash := sha256.New()
	n, err := io.Copy(io.MultiWriter(temp, hash), io.LimitReader(source, maxBinaryBytes+1))
	if err != nil || n < 1 || n > maxBinaryBytes {
		return "", errors.New("client-snapshot: source size or copy failure")
	}
	digest := hash.Sum(nil)
	if _, err = source.Seek(0, io.SeekStart); err != nil {
		return "", err
	}
	again := sha256.New()
	size, err := io.Copy(again, io.LimitReader(source, maxBinaryBytes+1))
	if err != nil || size != n || !bytes.Equal(again.Sum(nil), digest) {
		return "", errors.New("client-snapshot: source changed while preserving")
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
	encoded := hex.EncodeToString(digest)
	dir := filepath.Join(root, encoded)
	if err = privateDirectory(dir); err != nil {
		return "", err
	}
	name := "siq-agent-security"
	if goos == "windows" {
		name += ".exe"
	}
	result = filepath.Join(dir, name)
	if err = publish(temp.Name(), result, n, encoded, 0700); err != nil {
		return "", err
	}
	return result, nil
}
