package state

import (
	"path/filepath"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/statefs"
)

// CheckPrivateCredentials is a read-only guard for the daemon's cached Windows
// credentials. Missing files are failures; this never calls a creating accessor.
func (s *Store) CheckPrivateCredentials() error {
	if runtime.GOOS != "windows" {
		return nil
	}
	if err := statefs.CheckPrivateDir(s.Dir); err != nil {
		return err
	}
	for _, name := range []string{"token", recoveryFile} {
		if err := statefs.CheckPrivateFile(filepath.Join(s.Dir, name)); err != nil {
			return err
		}
	}
	return nil
}
