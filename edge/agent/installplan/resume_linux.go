//go:build linux

package installplan

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"syscall"
)

func VerifyStagedBundle(plan Plan, raw []byte, root string) error {
	r, err := VerifyPlanRelease(plan, raw)
	if err != nil {
		return ErrInvalid
	}
	return verifyStagedFiles(plan, raw, r, root)
}

func verifyStagedFiles(plan Plan, raw []byte, release *Release, root string) error {
	fd, err := openDirectory(root)
	if err != nil {
		return ErrInvalid
	}
	defer syscall.Close(fd)
	var stat syscall.Stat_t
	if syscall.Fstat(fd, &stat) != nil || int(stat.Uid) != os.Geteuid() || stat.Mode&0077 != 0 {
		return ErrInvalid
	}
	h := sha256.Sum256(raw)
	for name, expected := range map[string][]byte{
		"release.json": raw, "READY": []byte(hex.EncodeToString(h[:]) + "\n"),
	} {
		if err := matchStageMetadata(fd, name, expected); err != nil {
			return ErrInvalid
		}
	}
	for _, a := range selectedArtifacts(plan, release) {
		if err := verifyArtifact(fd, a); err != nil {
			return ErrInvalid
		}
	}
	return nil
}

func matchStageMetadata(parent int, name string, expected []byte) error {
	fd, err := syscall.Openat(parent, name, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0)
	if err != nil {
		return ErrInvalid
	}
	f := os.NewFile(uintptr(fd), "stage-metadata")
	defer f.Close()
	var stat syscall.Stat_t
	if syscall.Fstat(fd, &stat) != nil || stat.Mode&syscall.S_IFMT != syscall.S_IFREG || stat.Nlink != 1 || int(stat.Uid) != os.Geteuid() || stat.Mode&07777 != 0400 || stat.Size != int64(len(expected)) {
		return ErrInvalid
	}
	raw, err := io.ReadAll(io.LimitReader(f, int64(len(expected))+1))
	if err != nil || !bytes.Equal(raw, expected) {
		return ErrInvalid
	}
	return nil
}
