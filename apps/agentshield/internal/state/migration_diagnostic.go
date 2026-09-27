package state

import (
	"errors"
	"fmt"
	"path/filepath"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/privatefs"
)

// MigrationObjectError identifies the rejected relative object, never its
// bytes, ACL principals or an ambient absolute path. It is not a repair grant.
type MigrationObjectError struct {
	Code   string
	Object string
	cause  error
}

func (e *MigrationObjectError) Error() string {
	return fmt.Sprintf("state-migrate: %s (object %q); preserve state and external aliases", e.Code, e.Object)
}
func (e *MigrationObjectError) Unwrap() error { return e.cause }

func migrationObjectError(object string, err error) error {
	code := "state_migration_source_unavailable"
	switch {
	case errors.Is(err, privatefs.ErrMultipleLinks):
		code = "state_migration_multiple_links"
	case errors.Is(err, privatefs.ErrReparse):
		code = "state_migration_reparse"
	case errors.Is(err, privatefs.ErrOwnerMismatch):
		code = "state_migration_owner_mismatch"
	case errors.Is(err, privatefs.ErrObjectChanged):
		code = "state_migration_source_changed"
	case errors.Is(err, privatefs.ErrPrivate):
		code = "state_migration_private_permissions"
	}
	if !filepath.IsLocal(object) || len(object) > 4096 {
		object = "unknown"
	}
	return &MigrationObjectError{Code: code, Object: filepath.ToSlash(object), cause: err}
}

func readMigrationSource(path string, limit int64) ([]byte, error) {
	if runtime.GOOS != "windows" {
		return privatefs.ReadFile(path, limit)
	}
	snapshot, err := privatefs.OpenReadSnapshot(filepath.Dir(path))
	if err != nil {
		return nil, err
	}
	defer snapshot.Close()
	raw, err := snapshot.ReadFile(filepath.Base(path), limit)
	if err != nil {
		return nil, err
	}
	if err := snapshot.Verify(); err != nil {
		return nil, err
	}
	return raw, nil
}
