package state

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
)

// DirectoryID identifies a canonical existing directory without creating state.
// It is a locator digest, not an authentication or permanent device identity.
func (s *Store) DirectoryID() (string, error) {
	if s.Dir == "" {
		return "", errors.New("state: directory required")
	}
	path, err := filepath.Abs(s.Dir)
	if err == nil {
		path, err = filepath.EvalSymlinks(path)
	}
	if err != nil {
		return "", errors.New("state: directory unavailable; initialize the selected state directory first")
	}
	info, err := os.Stat(path)
	if err != nil || !info.IsDir() {
		return "", errors.New("state: directory unavailable; initialize the selected state directory first")
	}
	digest := sha256.Sum256([]byte("local-state-directory/v1\x00" + path))
	return hex.EncodeToString(digest[:]), nil
}
