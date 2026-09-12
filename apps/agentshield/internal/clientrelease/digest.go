package clientrelease

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
)

// Digest observes bounded regular-file bytes; it does not confer release trust.
func Digest(path string) (string, error) {
	f, err := openRegular(path, maxBinaryBytes)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	n, err := io.Copy(h, io.LimitReader(f, maxBinaryBytes+1))
	if err != nil || n < 1 || n > maxBinaryBytes {
		return "", errors.New("client-release: invalid binary content")
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
