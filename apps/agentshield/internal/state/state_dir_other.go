//go:build !windows

package state

import "siq-agent-security/apps/agentshield/internal/product"

func stateDirOverride() (string, error) {
	return product.Env(product.EnvStateDir, product.EnvStateDirOld), nil
}
