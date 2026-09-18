package skillinstall

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/fileopen"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

func openPrivateMetadata(path string) (*os.File, error) {
	if runtime.GOOS == "windows" {
		return statefs.OpenPrivate(path)
	}
	return fileopen.Regular(path)
}

func (s *Store) checkPrivateMetadataRoot() error {
	if runtime.GOOS != "windows" {
		return nil
	}
	if s.authority == nil {
		return ErrInvalid
	}
	for _, path := range []string{s.authority.Dir, s.dir} {
		if err := statefs.CheckPrivateDir(path); err != nil {
			return ErrChanged
		}
	}
	return nil
}

func checkExistingPrivateMetadata(path string) error {
	if runtime.GOOS != "windows" {
		return nil
	}
	if err := statefs.CheckPrivateFile(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return ErrChanged
	}
	return nil
}

func publishPrivateMetadata(path string, raw []byte, pattern string) error {
	f, err := statefs.CreatePrivateTemp(filepath.Dir(path), pattern)
	if err != nil {
		return ErrUnavailable
	}
	created, err := f.Stat()
	if err != nil {
		_ = f.Close()
		return ErrUnavailable
	}
	if _, err = f.Write(raw); err == nil {
		err = f.Sync()
	}
	err = errors.Join(err, f.Close())
	if err != nil {
		return ErrUnavailable
	}
	moved, err := statefs.PublishPrivateNew(f.Name(), path, created)
	if err != nil {
		// Failed private scratch is retained; a replaced name is not ours to delete.
		if errors.Is(err, os.ErrExist) {
			return ErrConflict
		}
		return ErrUnavailable
	}
	if !moved {
		if err := statefs.Remove(f.Name()); err != nil {
			return ErrUnavailable
		}
	}
	return nil
}
