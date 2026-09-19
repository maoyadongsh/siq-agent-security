package statefs

import (
	"errors"
	"path/filepath"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

// ReadPrivateRecord is a bounded Windows record read, not a reusable authority
// cache. Both compatibility checks include every ancestor/nested state root.
func ReadPrivateRecord(root, path string, limit int64) ([]byte, error) {
	if runtime.GOOS != "windows" || limit <= 0 || stateformat.ValidatePath(root) != nil || stateformat.ValidatePath(path) != nil {
		return nil, privatefs.ErrPrivate
	}
	root, rootErr := filepath.Abs(root)
	path, pathErr := filepath.Abs(path)
	name, relErr := filepath.Rel(root, path)
	if rootErr != nil || pathErr != nil || relErr != nil || name == "." || !filepath.IsLocal(name) {
		return nil, privatefs.ErrPrivate
	}
	if err := stateformat.RequirePath(path, false); err != nil {
		return nil, err
	}
	snapshot, err := privatefs.OpenReadSnapshot(root)
	if err != nil {
		return nil, privatefs.ErrPrivate // Missing root is never an absent record.
	}
	defer snapshot.Close()
	if err := snapshot.PinDirectory(filepath.Dir(name)); err != nil {
		return nil, privatefs.ErrPrivate // Missing directory is not no revocation.
	}
	raw, readErr := snapshot.ReadFile(name, limit)
	// Even an absent record is reported only after the directory and current
	// compatibility boundary have passed their final checks.
	if err := stateformat.RequirePath(path, false); err != nil {
		return nil, err
	}
	if err := snapshot.Verify(); err != nil {
		return nil, err
	}
	if err := snapshot.Close(); err != nil {
		return nil, errors.Join(privatefs.ErrPrivate, err)
	}
	if readErr != nil {
		return nil, readErr
	}
	return raw, nil
}
