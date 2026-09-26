package main

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

// Only run after task consent checks; never resolve an executable via PATH.
func collectInstalledSkills(ctx context.Context, state *State, raw json.RawMessage) (protocol.SkillCollection, error) {
	var out protocol.SkillCollection
	var scope protocol.Scope
	if strictDiscoveryJSON(raw, &scope) != nil || len(scope.Roots) == 0 || protocol.ValidateScopeSafety(&scope) != nil {
		return out, errSkillExecution
	}
	if _, err := measureServiceCapabilities(ctx, state); err != nil {
		return out, errInstalledCapabilities
	}
	c, err := NewSubprocessConnector(ctx, filepath.Join(os.Getenv("SIQ_CONNECTOR_BIN_DIR"), "directory-connector"), SubprocessOptions{
		Name: "directory", Version: agentVersion, Timeout: 60 * time.Second,
		MaxOutputBytes: protocol.DefaultOutputLimitBytes, MaxStderrBytes: 1024,
	})
	if err != nil {
		return out, errSkillExecution
	}
	defer c.Close()
	caps, err := c.Describe(ctx)
	if err != nil || caps.NetworkAccess || !slices.Contains(caps.Objects, "skill_manifest") {
		return out, errInstalledCapabilities
	}
	validation, err := c.ValidateScope(ctx, &scope)
	if err != nil || !validation.Valid || len(validation.Errors) != 0 {
		return out, errSkillExecution
	}
	op := protocol.OpCollectSkills
	if slices.Contains(caps.Objects, "skill_manifest_ancestry_v2") {
		op = protocol.OpCollectSkillsV2
	}
	err = c.call(ctx, op, struct {
		Plan protocol.ScanPlan `json:"plan"`
	}{Plan: protocol.ScanPlan{Scope: &scope, Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 16 << 20}}}, &out)
	return out, err
}
