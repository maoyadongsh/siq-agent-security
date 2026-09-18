//go:build !windows

package runtimecheck

import (
	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/state"
	"testing"
)

func prepareRuntimeCheckFixtureState(t *testing.T, st *state.Store) {}
func runtimeCheckFixtureTarget(t *testing.T, target adapterinstall.RuntimeTarget) adapterinstall.RuntimeTarget {
	return target
}
