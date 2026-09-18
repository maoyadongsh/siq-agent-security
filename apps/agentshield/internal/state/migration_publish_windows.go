package state

import (
	"os"
	"siq-agent-security/apps/agentshield/internal/privatefs"
)

// Migration owns its compatibility barrier and calls the common private
// publication primitive directly. Other writers use the statefs wrapper.
func migrationPublishScratch(path, target string, created os.FileInfo) (bool, error) {
	return privatefs.PublishNew(path, target, created)
}
