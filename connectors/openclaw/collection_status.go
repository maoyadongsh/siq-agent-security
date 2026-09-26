package main

import (
	"errors"
	"os"
)

// Preserve the reason category without exporting configuration paths or raw errors.
func collectionReadError(err error) error {
	if errors.Is(err, os.ErrNotExist) {
		return errors.New("openclaw_config_missing")
	}
	if errors.Is(err, os.ErrPermission) {
		return errors.New("openclaw_config_permission_denied")
	}
	return errors.New("openclaw_config_unavailable")
}
