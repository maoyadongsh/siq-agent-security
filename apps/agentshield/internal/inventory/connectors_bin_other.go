//go:build !windows

package inventory

import (
	"os"
	"path/filepath"
)

func findConnectorBin(root, name string) (string, error) {
	cands := []string{
		filepath.Join(root, name, name+"-connector"),
		filepath.Join(root, name, name),
		filepath.Join(root, name+"-connector"),
		filepath.Join(root, name),
	}
	for _, p := range cands {
		st, err := os.Stat(p)
		if err != nil || st.IsDir() || st.Mode()&0o111 == 0 {
			continue
		}
		return p, nil
	}
	return "", os.ErrNotExist
}
