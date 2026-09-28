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
		if err != nil || !st.Mode().IsRegular() || !connectorAncestorsOrdinary(filepath.Dir(p)) {
			continue
		}
		return p, nil
	}
	return "", os.ErrNotExist
}

// A regular leaf does not make a redirected parent safe. Inspect through the
// volume root, including the explicit connector root and its ancestors.
// This is a discovery-time check, not atomic isolation from later replacements.
func connectorAncestorsOrdinary(path string) bool {
	for {
		info, err := os.Lstat(path)
		if err != nil || !info.IsDir() || info.Mode()&(os.ModeSymlink|os.ModeIrregular) != 0 {
			return false
		}
		parent := filepath.Dir(path)
		if parent == path {
			return true
		}
		path = parent
	}
}
