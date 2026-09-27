package main

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"

	"siq-agent-security/apps/agentshield/internal/fileopen"
	"siq-agent-security/apps/agentshield/internal/state"
)

type migrationCommandPreview struct {
	state.MigrationPreview
	ExecutablePath    string `json:"executable_path"`
	ExecutableSHA256  string `json:"executable_sha256"`
	InvocationBinding string `json:"invocation_binding"`
}

type migrationInvocation struct{ DirectoryID, ExecutablePath, ExecutableSHA256, Binding string }

func inspectMigrationInvocation(dir string) (migrationInvocation, error) {
	exe, err := os.Executable()
	if err != nil {
		return migrationInvocation{}, errors.New("state-migrate: executable unavailable")
	}
	return inspectMigrationExecutable(dir, exe)
}

func inspectMigrationExecutable(dir, exe string) (migrationInvocation, error) {
	var result migrationInvocation
	var err error
	result.DirectoryID, err = (&state.Store{Dir: dir}).DirectoryID()
	if err != nil {
		return result, err
	}
	if !filepath.IsAbs(exe) || filepath.Clean(exe) != exe {
		return result, errors.New("state-migrate: canonical executable required")
	}
	for path := exe; ; path = filepath.Dir(path) {
		info, err := os.Lstat(path)
		if err != nil || info.Mode()&os.ModeSymlink != 0 {
			return result, errors.New("state-migrate: executable path unavailable")
		}
		if path == filepath.Dir(path) {
			break
		}
	}
	f, err := fileopen.Regular(exe)
	if err != nil {
		return result, errors.New("state-migrate: executable unavailable")
	}
	defer f.Close()
	before, err := f.Stat()
	if err != nil || !before.Mode().IsRegular() || before.Size() > 512<<20 {
		return result, errors.New("state-migrate: executable unavailable")
	}
	h := sha256.New()
	n, err := io.Copy(h, io.LimitReader(f, (512<<20)+1))
	after, statErr := f.Stat()
	current, pathErr := os.Lstat(exe)
	if err != nil || statErr != nil || pathErr != nil || n != before.Size() || !os.SameFile(before, current) || before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) {
		return result, errors.New("state-migrate: executable changed")
	}
	result.ExecutablePath = exe
	result.ExecutableSHA256 = hex.EncodeToString(h.Sum(nil))
	binding := sha256.Sum256([]byte("state-migration-invocation/v1\x00" + result.DirectoryID + "\x00" + exe + "\x00" + result.ExecutableSHA256))
	result.Binding = hex.EncodeToString(binding[:])
	return result, nil
}
