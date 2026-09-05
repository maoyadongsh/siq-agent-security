package main

import (
	"os"
	"strings"

	"siq-agent-security/apps/agentshield/internal/inventory"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func resolveConnectorsDir(flagVal string) string {
	if s := strings.TrimSpace(flagVal); s != "" {
		return s
	}
	return strings.TrimSpace(os.Getenv("SIQ_AS_CONNECTORS_DIR"))
}

func runLocalInventory(st *state.Store, key *signing.Key, cwd, connectorsDir string) (*inventory.Report, error) {
	admissions, _ := st.ListAdmissions()
	byHash := map[string]string{}
	for _, a := range admissions {
		byHash[a.ContentHash] = a.Verdict
	}
	return inventory.Run(inventory.Options{
		Cwd:           cwd,
		Version:       Version,
		Key:           key,
		ConnectorsDir: connectorsDir,
		HasAdmission:  func(h string) (string, bool) { v, ok := byHash[h]; return v, ok },
	})
}
