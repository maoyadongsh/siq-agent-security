package stateformat

import (
	"os"
	"path/filepath"
	"strings"
)

// ValidatePath checks the caller's spelling before cleaning or filesystem I/O.
// Empty paths and navigation retain the caller's rules. This does not validate
// general Windows path syntax or permissions.
func ValidatePath(path string) error {
	start := len(filepath.VolumeName(path))
	// VolumeName includes UNC host and share. Only the host is an authority;
	// the share itself is subject to the state-root component spelling policy.
	separators := strings.ReplaceAll(path, "/", `\`)
	hostStart := -1
	switch {
	case len(separators) >= 8 && (strings.EqualFold(separators[:8], `\\?\UNC\`) || strings.EqualFold(separators[:8], `\\.\UNC\`) || strings.EqualFold(separators[:8], `\??\UNC\`)):
		hostStart = 8
	case strings.HasPrefix(separators, `\\`) && !strings.HasPrefix(separators, `\\?\`) && !strings.HasPrefix(separators, `\\.\`):
		hostStart = 2
	}
	if hostStart >= 0 {
		if end := strings.IndexByte(separators[hostStart:], '\\'); end >= 0 {
			share := separators[hostStart+end+1:]
			if end := strings.IndexByte(share, '\\'); end >= 0 {
				share = share[:end]
			}
			if badPathTail(share) {
				return ErrCorrupt
			}
		}
	}
	for i := start; i <= len(path); i++ {
		if i < len(path) && !os.IsPathSeparator(path[i]) {
			continue
		}
		component := path[start:i]
		if component != "." && component != ".." && badPathTail(component) {
			return ErrCorrupt
		}
		start = i + 1
	}
	return nil
}

func badPathTail(component string) bool {
	return len(component) != 0 && (component[len(component)-1] == ' ' || component[len(component)-1] == '.')
}
