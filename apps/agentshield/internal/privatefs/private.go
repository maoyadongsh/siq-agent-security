// Package privatefs implements the Windows private-object boundary. The
// statefs callers remain responsible for state compatibility and access scope.
// Non-Windows calls retain the existing os permission semantics.
package privatefs

import (
	"errors"
	"io"
	"os"
)

var ErrPrivate = errors.New("private-state: unsafe or unverifiable permissions")

func ReadFile(path string, limit int64) ([]byte, error) {
	if limit <= 0 {
		return nil, ErrPrivate
	}
	f, err := Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(b)) > limit {
		return nil, ErrPrivate
	}
	return b, nil
}

// CheckFilePath verifies permissions without reading file contents.
func CheckFilePath(path string) error {
	f, err := Open(path)
	if err != nil {
		return err
	}
	return f.Close()
}

// CheckFile checks the already opened object before any secret is read.
func CheckFile(f *os.File) error { return checkFile(f, false) }
