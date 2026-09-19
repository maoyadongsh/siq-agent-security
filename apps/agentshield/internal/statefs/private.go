package statefs

import (
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func ReadPrivateFile(path string, limit int64) ([]byte, error) {
	if err := stateformat.RequirePath(path, false); err != nil {
		return nil, err
	}
	if err := privatefs.CheckDir(filepath.Dir(path)); err != nil {
		return nil, err
	}
	return privatefs.ReadFile(path, limit)
}
func OpenPrivate(path string) (*os.File, error) {
	if err := stateformat.RequirePath(path, false); err != nil {
		return nil, err
	}
	if err := privatefs.CheckDir(filepath.Dir(path)); err != nil {
		return nil, err
	}
	return privatefs.Open(path)
}

// OpenPrivateDir checks the directory handle that the caller will enumerate.
func OpenPrivateDir(path string) (*os.File, error) {
	if err := stateformat.RequirePath(path, false); err != nil {
		return nil, err
	}
	return privatefs.OpenDir(path)
}

// CheckPrivateFile validates the opened object without reading secret bytes.
func CheckPrivateFile(path string) error {
	f, err := OpenPrivate(path)
	if err != nil {
		return err
	}
	return f.Close()
}
func CreatePrivate(path string) (*os.File, error) {
	if err := stateformat.RequirePath(path, true); err != nil {
		return nil, err
	}
	return privatefs.CreateNew(path)
}
func CreatePrivateTemp(dir, pattern string) (*os.File, error) {
	if err := stateformat.RequirePath(dir, true); err != nil {
		return nil, err
	}
	return privatefs.CreateTemp(dir, pattern)
}
func MkdirAllPrivate(path string) error {
	if err := stateformat.RequirePath(path, true); err != nil {
		return err
	}
	return privatefs.MkdirAll(path)
}
func CheckPrivateDir(path string) error {
	if err := stateformat.RequirePath(path, false); err != nil {
		return err
	}
	return privatefs.CheckDir(path)
}

// PublishPrivateNew retains the compatibility barrier for both names. The
// caller owns scratch cleanup when moved is false; existing targets survive.
func PublishPrivateNew(source, target string, created os.FileInfo) (bool, error) {
	if err := stateformat.RequirePath(source, true); err != nil {
		return false, err
	}
	if err := stateformat.RequirePath(target, true); err != nil {
		return false, err
	}
	return privatefs.PublishNew(source, target, created)
}
