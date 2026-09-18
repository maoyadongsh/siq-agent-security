//go:build !windows

package state

import (
	"errors"
	"os"
)

func migrationRemoveScratch(path string, created os.FileInfo) error {
	actual, err := os.Lstat(path)
	if err != nil || !actual.Mode().IsRegular() || !os.SameFile(created, actual) {
		return errors.New("state-migrate: scratch identity changed")
	}
	return os.Remove(path)
}
