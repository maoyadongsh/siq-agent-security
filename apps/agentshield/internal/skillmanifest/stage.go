package skillmanifest

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// StageVerifiedBinary copies src into a private 0700 directory under stageRoot,
// Syncs the copy, then re-hashes it (DEV04-D).
//
// wantSHA256, when non-empty, must match both the source digest taken before
// copy and the staged digest after copy. When empty, only source==staged is
// required (detects replace/corruption during copy).
//
// The returned path is the staged file; callers should execute that path, not src.
func StageVerifiedBinary(src, stageRoot, wantSHA256 string) (stagedPath string, err error) {
	info, err := os.Lstat(src)
	if err != nil {
		return "", err
	}
	if !info.Mode().IsRegular() {
		return "", fmt.Errorf("skillmanifest: stage source must be a regular file")
	}
	if info.Mode()&0o111 == 0 {
		return "", fmt.Errorf("skillmanifest: stage source is not executable")
	}
	srcSum, err := HashFileDigest(src)
	if err != nil {
		return "", err
	}
	want := normalizeHex(wantSHA256)
	if want != "" && srcSum != want {
		return "", fmt.Errorf("skillmanifest: source sha256 %s != required %s", srcSum, want)
	}
	if err := os.MkdirAll(stageRoot, 0o700); err != nil {
		return "", err
	}
	dir, err := os.MkdirTemp(stageRoot, "bin.*")
	if err != nil {
		return "", err
	}
	cleanup := true
	defer func() {
		if cleanup {
			_ = os.RemoveAll(dir)
		}
	}()
	if err := os.Chmod(dir, 0o700); err != nil {
		return "", err
	}
	leaf := filepath.Base(src)
	if leaf == "." || leaf == string(filepath.Separator) {
		return "", fmt.Errorf("skillmanifest: invalid binary basename")
	}
	dest := filepath.Join(dir, leaf)
	if err := copyFileExclusive(src, dest, 0o700); err != nil {
		return "", err
	}
	stagedSum, err := HashFileDigest(dest)
	if err != nil {
		return "", err
	}
	if stagedSum != srcSum {
		return "", fmt.Errorf("skillmanifest: staged sha256 %s != source %s (refusing TOCTOU/corrupt copy)", stagedSum, srcSum)
	}
	if want != "" && stagedSum != want {
		return "", fmt.Errorf("skillmanifest: staged sha256 %s != required %s", stagedSum, want)
	}
	cleanup = false
	return dest, nil
}

// HashFileDigest returns the sha256 hex digest of a regular file.
func HashFileDigest(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return "", err
	}
	if !st.Mode().IsRegular() {
		return "", fmt.Errorf("skillmanifest: not a regular file")
	}
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func copyFileExclusive(src, dest string, mode os.FileMode) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(dest, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		_ = out.Close()
		_ = os.Remove(dest)
		return err
	}
	if err := out.Sync(); err != nil {
		_ = out.Close()
		_ = os.Remove(dest)
		return err
	}
	if err := out.Close(); err != nil {
		_ = os.Remove(dest)
		return err
	}
	return nil
}

func normalizeHex(s string) string {
	out := make([]byte, 0, len(s))
	for i := 0; i < len(s); i++ {
		c := s[i]
		if c >= 'A' && c <= 'F' {
			c = c - 'A' + 'a'
		}
		if (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') {
			out = append(out, c)
		}
	}
	return string(out)
}
