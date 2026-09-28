//go:build !windows

package workbuddycorrelation

import (
	"os"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

func releaseOwnedLock(path string, created os.FileInfo) {
	f, err := statefs.OpenPrivate(path)
	if err != nil {
		return
	}
	info, statErr := f.Stat()
	closeErr := f.Close()
	if statErr == nil && closeErr == nil && os.SameFile(created, info) {
		_ = statefs.Remove(path)
	}
}
