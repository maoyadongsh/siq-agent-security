package state

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"runtime"
)

const recoveryFile = "admin-recovery.token"

// ReadRecoveryToken never creates state. CLI callers use it only after checking
// the loopback service identity. This credential is not an adapter token.
func (s *Store) ReadRecoveryToken() (string, error) {
	p := filepath.Join(s.Dir, recoveryFile)
	info, err := os.Lstat(p)
	if err != nil {
		return "", err
	}
	if !info.Mode().IsRegular() || info.Size() != 64 || (runtime.GOOS != "windows" && info.Mode().Perm()&0o077 != 0) {
		return "", errors.New("state: invalid recovery credential file or permissions")
	}
	raw, err := os.ReadFile(p)
	if err != nil {
		return "", err
	}
	decoded, err := hex.DecodeString(string(raw))
	if err != nil || len(decoded) != 32 {
		return "", errors.New("state: invalid recovery credential")
	}
	return string(raw), nil
}

// RecoveryToken creates a private, independent credential at serve startup.
func (s *Store) RecoveryToken() (string, error) {
	if tok, err := s.ReadRecoveryToken(); !errors.Is(err, os.ErrNotExist) {
		return tok, err
	}
	var raw [32]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return "", err
	}
	token := hex.EncodeToString(raw[:])
	if err := writeDurable(filepath.Join(s.Dir, recoveryFile), []byte(token)); err != nil {
		if errors.Is(err, ErrConflict) {
			return s.ReadRecoveryToken()
		}
		return "", err
	}
	return token, nil
}
