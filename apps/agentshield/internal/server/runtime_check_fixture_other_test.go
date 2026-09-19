//go:build !windows

package server

import (
	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"testing"
)

func newRuntimeCheckHTTPServer(t *testing.T) *Server { s, _ := newServer(t, "block"); return s }
func runtimeCheckHTTPFixtureTarget(t *testing.T, target adapterinstall.RuntimeTarget) adapterinstall.RuntimeTarget {
	t.Helper()
	return target
}
