package adapterinstall

import (
	"errors"
	"path/filepath"

	"siq-agent-security/apps/agentshield/internal/statefs"
)

// Private recovery data must not inherit host configuration write semantics.
func publishRecoveryFile(path string, raw []byte) (resultErr error) {
	parent := filepath.Dir(path)
	if err := statefs.MkdirAllPrivate(parent); err != nil {
		return err
	}
	f, err := statefs.CreatePrivateTemp(parent, ".siq-adapter-private-*")
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
	err = errors.Join(err, f.Close())
	if err != nil {
		return err
	}
	moved, err := statefs.PublishPrivateNew(f.Name(), path, created)
	if err != nil {
		// Retain failed private scratch: the name may have been replaced, so
		// it must not be deleted merely because this attempt created it.
		return err
	}
	if !moved {
		return statefs.Remove(f.Name()) // non-Windows exclusive hard-link publication
	}
	return nil
}
