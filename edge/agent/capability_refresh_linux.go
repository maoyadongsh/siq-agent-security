//go:build linux

package main

import (
	"context"
	"os"
	"path/filepath"
	"runtime"

	"siq-agent-security/edge/agent/installplan"
)

func measureServiceCapabilities(ctx context.Context, state *State) (map[string]any, error) {
	return measureServiceCapabilitiesAt(ctx, state, os.Getenv("SIQ_CONNECTOR_BIN_DIR"), installplan.VerifyStagedBundle, probeInstalledConnector)
}

func measureServiceCapabilitiesAt(ctx context.Context, state *State, binDir string, verify func(installplan.Plan, []byte, string) error, probe capabilityProbe) (map[string]any, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	digest, err := compactPlanDigest(state.DiscoveryPlan)
	if err != nil || digest != state.DiscoveryPlanSHA256 {
		return nil, errInstalledCapabilities
	}
	p, err := installplan.Parse(state.DiscoveryPlan)
	// Consent persists after the short enrollment deadline; do not reapply expiry.
	if err != nil || p.EnvironmentID != state.EnvironmentID || p.ControlPlaneOrigin != state.ControlPlaneURL || p.TargetArch != runtime.GOARCH || p.ServiceMode != "user" {
		return nil, errInstalledCapabilities
	}
	if !filepath.IsAbs(binDir) || filepath.Clean(binDir) != binDir {
		return nil, errInstalledCapabilities
	}
	stage := filepath.Dir(filepath.Dir(binDir))
	if filepath.Join(stage, "bin", p.TargetArch) != binDir {
		return nil, errInstalledCapabilities
	}
	raw, err := readInstallDocument(filepath.Join(stage, "release.json"))
	if err != nil || verify(*p, raw, stage) != nil {
		return nil, errInstalledCapabilities
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	return installedCapabilities(ctx, stage, p, probe)
}
