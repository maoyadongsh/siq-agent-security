package server

import (
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
)

func makeEvidenceDirectoryReadOnly(t *testing.T, root, path string) func() {
	t.Helper()
	return acltest.DenyCreate(t, root, path)
}
