package inventory

import (
	"os"
	"path/filepath"
)

func findConnectorBin(root, name string) (string, error) {
	// An explicit root must stay explicit even when root == ".": returning a
	// bare filename would let exec.Command consult PATH on Windows.
	absRoot, err := filepath.Abs(root)
	if err != nil {
		return "", err
	}
	cands := []string{
		filepath.Join(absRoot, name, name+"-connector.exe"),
		filepath.Join(absRoot, name, name+".exe"),
		filepath.Join(absRoot, name+"-connector.exe"),
		filepath.Join(absRoot, name+".exe"),
	}
	for _, p := range cands {
		st, err := os.Lstat(p)
		if err != nil || !st.Mode().IsRegular() {
			continue
		}
		return p, nil
	}
	return "", os.ErrNotExist
}
