//go:build linux

package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"

	"siq-agent-security/edge/agent/installplan"
)

func connectorCommand(ctx context.Context, path, name, digest string) (*exec.Cmd, *os.File, error) {
	if digest == "" {
		return exec.CommandContext(ctx, path, "--serve"), nil, nil
	}
	f, err := openVerifiedConnector(path, name, digest)
	if err != nil {
		return nil, nil, ErrConnectorTrust
	}
	cmd := exec.CommandContext(ctx, "/proc/self/fd/3", "--serve")
	cmd.ExtraFiles = []*os.File{f}
	return cmd, f, nil
}

func openVerifiedConnector(path, name, digest string) (*os.File, error) {
	if !isOfficialConnector(name) || !regexp.MustCompile(`^[0-9a-f]{64}$`).MatchString(digest) ||
		!filepath.IsAbs(path) || filepath.Clean(path) != path || filepath.Base(path) != name+"-connector" || len(path) > 4096 {
		return nil, ErrConnectorTrust
	}
	parts := strings.Split(strings.TrimPrefix(path, "/"), "/")
	if len(parts) > 128 {
		return nil, ErrConnectorTrust
	}
	fd, err := syscall.Open("/", syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, ErrConnectorTrust
	}
	defer func() {
		if fd >= 0 {
			syscall.Close(fd)
		}
	}()
	for i, part := range parts {
		var parent syscall.Stat_t
		if syscall.Fstat(fd, &parent) != nil ||
			(int(parent.Uid) != os.Geteuid() && parent.Uid != 0) ||
			(parent.Mode&0022 != 0 && !(parent.Uid == 0 && parent.Mode&syscall.S_ISVTX != 0)) {
			return nil, ErrConnectorTrust
		}
		flags := syscall.O_RDONLY | syscall.O_NOFOLLOW | syscall.O_CLOEXEC | syscall.O_NONBLOCK
		if i < len(parts)-1 {
			flags |= syscall.O_DIRECTORY
		}
		next, err := syscall.Openat(fd, part, flags, 0)
		if err != nil {
			return nil, ErrConnectorTrust
		}
		syscall.Close(fd)
		fd = next
	}
	f := os.NewFile(uintptr(fd), "verified-connector")
	fd = -1
	valid := false
	defer func() {
		if !valid {
			f.Close()
		}
	}()
	var before, after syscall.Stat_t
	if syscall.Fstat(int(f.Fd()), &before) != nil || before.Mode&syscall.S_IFMT != syscall.S_IFREG ||
		before.Nlink != 1 || int(before.Uid) != os.Geteuid() || before.Mode&07777 != 0500 ||
		before.Size < 4 || before.Size > 256<<20 {
		return nil, ErrConnectorTrust
	}
	var magic [4]byte
	if _, err := f.ReadAt(magic[:], 0); err != nil || string(magic[:]) != "\x7fELF" {
		return nil, ErrConnectorTrust
	}
	hash := sha256.New()
	n, err := io.Copy(hash, io.LimitReader(f, before.Size+1))
	if err != nil || n != before.Size || hex.EncodeToString(hash.Sum(nil)) != digest ||
		syscall.Fstat(int(f.Fd()), &after) != nil || !sameConnectorStat(before, after) {
		return nil, ErrConnectorTrust
	}
	if _, err := f.Seek(0, 0); err != nil {
		return nil, ErrConnectorTrust
	}
	valid = true
	return f, nil
}

func sameConnectorStat(a, b syscall.Stat_t) bool {
	return a.Dev == b.Dev && a.Ino == b.Ino && a.Mode == b.Mode && a.Nlink == b.Nlink &&
		a.Uid == b.Uid && a.Gid == b.Gid && a.Size == b.Size && a.Mtim == b.Mtim && a.Ctim == b.Ctim
}

func resolveManagedConnector(state *State, name string) (string, string, error) {
	if !isOfficialConnector(name) {
		return "", "", ErrConnectorTrust
	}
	p, stage, err := verifiedServicePlan(state, os.Getenv("SIQ_CONNECTOR_BIN_DIR"), installplan.VerifyStagedBundle)
	if err != nil {
		return "", "", ErrConnectorTrust
	}
	for _, selected := range p.Connectors {
		if selected.ID == name {
			return filepath.Join(stage, "bin", p.TargetArch, name+"-connector"), selected.ArtifactSHA256, nil
		}
	}
	return "", "", ErrConnectorTrust
}
