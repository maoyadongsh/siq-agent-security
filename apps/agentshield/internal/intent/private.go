package intent

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/statefs"
)

func checkRecordDirectory(dir string) error {
	if runtime.GOOS != "windows" {
		return nil
	}
	for _, path := range []string{filepath.Dir(dir), dir} {
		if err := statefs.CheckPrivateDir(path); err != nil {
			// Missing/unreadable metadata directories are not an absent record.
			return violation("intent_state_unavailable")
		}
	}
	return nil
}

func openRecord(path string) (*os.File, error) {
	if runtime.GOOS != "windows" {
		return statefs.Open(path)
	}
	if err := checkRecordDirectory(filepath.Dir(path)); err != nil {
		return nil, err
	}
	return statefs.OpenPrivate(path)
}

func readPrivateRecord(path string) ([]byte, error) {
	return statefs.ReadPrivateRecord(filepath.Dir(filepath.Dir(path)), path, maxRecordBytes)
}

func openRecords(dir string) (*os.File, error) {
	if runtime.GOOS != "windows" {
		return statefs.Open(dir)
	}
	if err := checkRecordDirectory(dir); err != nil {
		return nil, err
	}
	return statefs.OpenPrivateDir(dir)
}

func publishPrivateRecord(path string, raw []byte) error {
	if err := checkRecordDirectory(filepath.Dir(path)); err != nil {
		return err
	}
	// An existing target is re-read and verified by the caller. Ordinary
	// idempotent retries must not allocate abandoned private scratch files.
	if _, err := os.Lstat(path); err == nil {
		return os.ErrExist
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	f, err := statefs.CreatePrivateTemp(filepath.Dir(path), ".intent-*")
	if err != nil {
		return err
	}
	created, err := f.Stat()
	if err != nil {
		_ = f.Close()
		return err
	}
	if _, err = f.Write(raw); err == nil {
		err = f.Sync()
	}
	if err = errors.Join(err, f.Close()); err != nil {
		return err
	}
	// Windows moves the known file. Failed scratch is retained, never deleted
	// by a name that could now designate an unknown object.
	_, err = statefs.PublishPrivateNew(f.Name(), path, created)
	return err
}
