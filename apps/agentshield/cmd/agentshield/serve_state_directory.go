package main

import (
	"errors"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func serveStateDirectory(selected string, explicit bool) (string, error) {
	if !explicit {
		return stateDir()
	}
	invalid := errors.New("serve: --state-dir requires an existing canonical absolute directory")
	if selected == "" || !filepath.IsAbs(selected) || filepath.Clean(selected) != selected {
		return "", invalid
	}
	info, err := os.Lstat(selected)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return "", invalid
	}
	if err := stateformat.LeafDirectory(selected); err != nil {
		return "", invalid
	}
	return selected, nil
}
