package signing

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

var ErrIdentityMissing = errors.New("signing: identity_missing_restore_required; restore the original signing key from a trusted backup")

// Missing identity is not a request to rotate an established signing key.
// Only bootstrap metadata and empty directory skeletons may precede first use.
func requireInitialIdentityState(root string) error {
	info, err := os.Lstat(root)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil || !info.IsDir() {
		return ErrIdentityMissing
	}
	budget := 4096
	var visit func(string, int) error
	visit = func(dir string, depth int) error {
		if depth > 32 {
			return ErrIdentityMissing
		}
		f, err := statefs.Open(dir)
		if err != nil {
			return ErrIdentityMissing
		}
		defer f.Close()
		for {
			entries, e := f.Readdir(64)
			if e != nil && e != io.EOF {
				return ErrIdentityMissing
			}
			for _, entry := range entries {
				budget--
				if budget < 0 {
					return ErrIdentityMissing
				}
				if entry.IsDir() {
					if err := visit(filepath.Join(dir, entry.Name()), depth+1); err != nil {
						return err
					}
					continue
				}
				if depth == 0 && entry.Mode().IsRegular() {
					switch entry.Name() {
					case "config.json", "local-instance.json", "state-format.json", "serve.lock":
						continue
					}
				}
				return ErrIdentityMissing
			}
			if e == io.EOF {
				return nil
			}
		}
	}
	return visit(root, 0)
}
