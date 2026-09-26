//go:build linux

package installplan

import (
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
)

// VerifyBundle is a read-only preflight, not permission to execute or register.
// Activation must use separately verified private staging, never reopen these
// paths assuming this earlier check prevents later modification.
func VerifyBundle(plan Plan, raw []byte, root string) error {
	r, err := VerifyPlanRelease(plan, raw)
	if err != nil {
		return ErrInvalid
	}
	return verifyBundleFiles(plan, r, root)
}

// VerifyReleaseBundle verifies all signed artifacts, including architectures not
// native to this machine. It grants no installation scope and executes nothing.
func VerifyReleaseBundle(raw []byte, root string) (*Release, error) {
	r, err := VerifyRelease(raw)
	if err != nil {
		return nil, ErrInvalid
	}
	if err := verifyReleaseFiles(r, root); err != nil {
		return nil, ErrInvalid
	}
	return r, nil
}

func verifyReleaseFiles(release *Release, root string) error {
	fd, err := openDirectory(root)
	if err != nil {
		return ErrInvalid
	}
	defer syscall.Close(fd)
	for _, artifact := range release.Artifacts {
		if err := verifyArtifact(fd, artifact); err != nil {
			return ErrInvalid
		}
	}
	return nil
}

func verifyBundleFiles(plan Plan, release *Release, root string) error {
	fd, err := openDirectory(root)
	if err != nil {
		return ErrInvalid
	}
	defer syscall.Close(fd)
	for _, a := range selectedArtifacts(plan, release) {
		if err := verifyArtifact(fd, a); err != nil {
			return ErrInvalid
		}
	}
	return nil
}

func openDirectory(root string) (int, error) {
	if !filepath.IsAbs(root) || filepath.Clean(root) != root || root == "/" {
		return -1, ErrInvalid
	}
	fd, err := syscall.Open("/", syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_CLOEXEC, 0)
	if err != nil {
		return -1, ErrInvalid
	}
	for _, part := range strings.Split(strings.TrimPrefix(root, "/"), "/") {
		next, openErr := syscall.Openat(fd, part, syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
		syscall.Close(fd)
		if openErr != nil {
			return -1, ErrInvalid
		}
		fd = next
	}
	return fd, nil
}

func selectedArtifacts(plan Plan, release *Release) []Artifact {
	var selected []Artifact
	wanted := map[string]bool{"edge-agent": true}
	for _, c := range plan.Connectors {
		wanted[c.ID] = true
	}
	for _, a := range release.Artifacts {
		if a.Arch != plan.TargetArch || !wanted[a.ID] {
			continue
		}
		selected = append(selected, a)
	}
	return selected
}

func verifyArtifact(rootFD int, a Artifact) error {
	f, err := openArtifact(rootFD, a)
	if err != nil {
		return ErrInvalid
	}
	defer f.Close()
	return copyArtifact(io.Discard, f, a)
}

func openArtifact(rootFD int, a Artifact) (*os.File, error) {
	// Paths have already passed the signed manifest's exact layout validation.
	fd, err := syscall.Dup(rootFD)
	if err != nil {
		return nil, ErrInvalid
	}
	syscall.CloseOnExec(fd)
	parts := strings.Split(a.Path, "/")
	for i, part := range parts {
		flags := syscall.O_RDONLY | syscall.O_NOFOLLOW | syscall.O_CLOEXEC | syscall.O_NONBLOCK
		if i < len(parts)-1 {
			flags |= syscall.O_DIRECTORY
		}
		next, openErr := syscall.Openat(fd, part, flags, 0)
		syscall.Close(fd)
		if openErr != nil {
			return nil, ErrInvalid
		}
		fd = next
	}
	f := os.NewFile(uintptr(fd), "artifact")
	var stat syscall.Stat_t
	if syscall.Fstat(fd, &stat) != nil || stat.Mode&syscall.S_IFMT != syscall.S_IFREG || stat.Nlink != 1 || stat.Size != a.Bytes || stat.Mode&0111 == 0 || stat.Mode&06022 != 0 {
		f.Close()
		return nil, ErrInvalid
	}
	return f, nil
}

func copyArtifact(dst io.Writer, src io.Reader, a Artifact) error {
	h := sha256.New()
	n, err := io.Copy(io.MultiWriter(dst, h), io.LimitReader(src, a.Bytes+1))
	if err != nil || n != a.Bytes || hex.EncodeToString(h.Sum(nil)) != a.SHA256 {
		return ErrInvalid
	}
	return nil
}
