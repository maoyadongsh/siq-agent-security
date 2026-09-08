//go:build unix

package admission

import (
	"os"
	"siq-agent-security/apps/agentshield/internal/fileopen"
)

func openRegular(path string) (*os.File, error) { return fileopen.Regular(path) }
