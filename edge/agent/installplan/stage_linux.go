//go:build linux

package installplan

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"path/filepath"
	"syscall"
)

// StageBundle never activates or executes the copied artifacts. The caller owns
// the stable private parent and must separately validate consent/current context.
func StageBundle(plan Plan, raw []byte, source, parent string) (string, error) {
	r, err := VerifyPlanRelease(plan, raw)
	if err != nil {
		return "", ErrInvalid
	}
	return stageBundle(plan, raw, r, source, parent)
}

func stageBundle(plan Plan, raw []byte, release *Release, source, parent string) (string, error) {
	src, err := openDirectory(source)
	if err != nil {
		return "", ErrInvalid
	}
	defer syscall.Close(src)
	base, err := openDirectory(parent)
	if err != nil {
		return "", ErrInvalid
	}
	defer syscall.Close(base)
	var stat syscall.Stat_t
	if syscall.Fstat(base, &stat) != nil || int(stat.Uid) != os.Geteuid() || stat.Mode&0077 != 0 {
		return "", ErrInvalid
	}
	var nonce [16]byte
	if _, err := rand.Read(nonce[:]); err != nil {
		return "", ErrInvalid
	}
	name := "stage-" + hex.EncodeToString(nonce[:])
	stage, err := newStageDir(base, name)
	if err != nil {
		return "", ErrInvalid
	}
	defer syscall.Close(stage)
	bin, err := newStageDir(stage, "bin")
	if err != nil {
		return "", ErrInvalid
	}
	defer syscall.Close(bin)
	arch, err := newStageDir(bin, plan.TargetArch)
	if err != nil {
		return "", ErrInvalid
	}
	defer syscall.Close(arch)
	for _, a := range selectedArtifacts(plan, release) {
		if err := stageArtifact(src, arch, a); err != nil {
			return "", ErrInvalid
		}
	}
	if syscall.Fsync(arch) != nil || syscall.Fsync(bin) != nil {
		return "", ErrInvalid
	}
	if err := stageMetadata(stage, "release.json", raw); err != nil {
		return "", ErrInvalid
	}
	hash := sha256.Sum256(raw)
	if err := stageMetadata(stage, "READY", []byte(hex.EncodeToString(hash[:])+"\n")); err != nil {
		return "", ErrInvalid
	}
	if syscall.Fsync(stage) != nil || syscall.Fsync(base) != nil {
		return "", ErrInvalid
	}
	return filepath.Join(parent, name), nil
}

func newStageDir(parent int, name string) (int, error) {
	if err := syscall.Mkdirat(parent, name, 0700); err != nil {
		return -1, ErrInvalid
	}
	fd, err := syscall.Openat(parent, name, syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if err != nil {
		return -1, ErrInvalid
	}
	return fd, nil
}

func newStageFile(parent int, name string) (*os.File, error) {
	fd, err := syscall.Openat(parent, name, syscall.O_RDWR|syscall.O_CREAT|syscall.O_EXCL|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0600)
	if err != nil {
		return nil, ErrInvalid
	}
	return os.NewFile(uintptr(fd), "staged-artifact"), nil
}

func stageArtifact(source, destination int, a Artifact) error {
	in, err := openArtifact(source, a)
	if err != nil {
		return ErrInvalid
	}
	defer in.Close()
	out, err := newStageFile(destination, filepath.Base(a.Path))
	if err != nil {
		return ErrInvalid
	}
	defer out.Close()
	if copyArtifact(out, in, a) != nil {
		return ErrInvalid
	}
	// Read back staged bytes rather than relying only on the source hash.
	if _, err := out.Seek(0, 0); err != nil {
		return ErrInvalid
	}
	if copyArtifact(io.Discard, out, a) != nil || out.Chmod(0500) != nil || out.Sync() != nil {
		return ErrInvalid
	}
	return nil
}

func stageMetadata(parent int, name string, raw []byte) error {
	f, err := newStageFile(parent, name)
	if err != nil {
		return ErrInvalid
	}
	defer f.Close()
	if n, err := f.Write(raw); err != nil || n != len(raw) {
		return ErrInvalid
	}
	if f.Chmod(0400) != nil || f.Sync() != nil {
		return ErrInvalid
	}
	return nil
}
