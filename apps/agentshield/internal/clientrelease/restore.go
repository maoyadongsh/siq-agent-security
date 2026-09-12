package clientrelease

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
)

// SnapshotPath locates an intact local observation, not a trusted release.
func SnapshotPath(directory, digest string) (string, error) {
	raw, err := hex.DecodeString(digest)
	if err != nil || len(raw) != 32 || hex.EncodeToString(raw) != digest {
		return "", errors.New("client-restore: invalid historical digest")
	}
	root := filepath.Join(directory, "client-snapshots")
	dir := filepath.Join(root, digest)
	for _, path := range []string{root, dir} {
		info, err := os.Lstat(path)
		if err != nil {
			return "", err
		}
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || (runtime.GOOS != "windows" && info.Mode().Perm() != 0700) {
			return "", errors.New("client-restore: unsafe snapshot directory")
		}
	}
	name := "siq-agent-security"
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	path := filepath.Join(dir, name)
	actual, err := Digest(path)
	if err != nil {
		return "", err
	}
	if actual != digest {
		return "", errors.New("client-restore: snapshot integrity mismatch")
	}
	return path, nil
}

// RestoreSnapshot publishes only to a missing destination. Caller must validate
// signed historical path ownership and release authenticity before calling.
func RestoreSnapshot(directory, digest, target string) error {
	sourcePath, err := SnapshotPath(directory, digest)
	if err != nil {
		return err
	}
	if !filepath.IsAbs(target) || filepath.Clean(target) != target {
		return errors.New("client-restore: canonical absolute target required")
	}
	parent := filepath.Dir(target)
	resolved, err := filepath.EvalSymlinks(parent)
	if err != nil {
		return err
	}
	if resolved != parent {
		return errors.New("client-restore: noncanonical target parent")
	}
	if _, err := os.Lstat(target); !errors.Is(err, os.ErrNotExist) {
		return errors.New("client-restore: destination is not missing")
	}
	source, err := openRegular(sourcePath, maxBinaryBytes)
	if err != nil {
		return err
	}
	defer source.Close()
	temp, err := os.CreateTemp(parent, ".siq-restore-*")
	if err != nil {
		return err
	}
	defer os.Remove(temp.Name())
	defer temp.Close()
	h := sha256.New()
	n, err := io.Copy(io.MultiWriter(temp, h), io.LimitReader(source, maxBinaryBytes+1))
	if err != nil || n < 1 || n > maxBinaryBytes || hex.EncodeToString(h.Sum(nil)) != digest {
		return errors.New("client-restore: snapshot changed while copying")
	}
	if err = temp.Chmod(0700); err != nil {
		return err
	}
	if err = temp.Sync(); err != nil {
		return err
	}
	if err = temp.Close(); err != nil {
		return err
	}
	// Unlike stage reuse, any destination that appears during copying is refused.
	if err = os.Link(temp.Name(), target); err != nil {
		return err
	}
	if runtime.GOOS != "windows" {
		d, err := os.Open(parent)
		if err != nil {
			return err
		}
		defer d.Close()
		return d.Sync()
	}
	return nil
}
