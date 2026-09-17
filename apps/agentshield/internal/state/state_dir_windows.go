package state

import (
	"os"

	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func stateDirOverride() (string, error) {
	for _, name := range []string{product.EnvStateDir, product.EnvStateDirOld} {
		if raw := os.Getenv(name); raw != "" {
			if err := stateformat.ValidatePath(raw); err != nil {
				return "", err
			}
			return raw, nil
		}
	}
	return "", nil
}
