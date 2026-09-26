//go:build linux

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"flag"
	"io"
	"runtime"
	"time"

	"siq-agent-security/edge/agent/installplan"
)

func cmdConfirmDiscovery(args []string) error {
	return confirmDiscovery(args, time.Now().UTC(), runtime.GOARCH)
}

func confirmDiscovery(args []string, now time.Time, arch string) error {
	fs := flag.NewFlagSet("confirm-discovery-plan", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	path := fs.String("plan", "", "")
	tenant := fs.String("tenant", "", "")
	confirmed := fs.String("confirm-plan-sha256", "", "")
	if fs.Parse(args) != nil || fs.NArg() != 0 {
		return errDiscoveryConsent
	}
	unlock, err := acquireTaskLock()
	if err != nil {
		return errDiscoveryConsent
	}
	defer unlock()
	statePath, err := StateFilePath()
	if err != nil {
		return errDiscoveryConsent
	}
	var state State
	if readPrivateJSON(statePath, &state, installplan.MaxBytes+8192) != nil || state.DeviceIdentity == "" || state.Secret == "" {
		return errDiscoveryConsent
	}
	raw, err := readInstallDocument(*path)
	if err != nil {
		return errDiscoveryConsent
	}
	h := sha256.Sum256(raw)
	if *confirmed != hex.EncodeToString(h[:]) {
		return errDiscoveryConsent
	}
	p, err := installplan.Parse(raw)
	if err != nil || p.RequireCurrent(now, *tenant, state.EnvironmentID, state.ControlPlaneURL, arch) != nil {
		return errDiscoveryConsent
	}
	state.DiscoveryPlan = raw
	state.DiscoveryPlanSHA256, err = compactPlanDigest(raw)
	if err != nil {
		return errDiscoveryConsent
	}
	if state.Save() != nil {
		return errDiscoveryConsent
	}
	dir, err := StateDir()
	if err != nil || syncRegistrationDirectory(dir) != nil {
		return errDiscoveryConsent
	}
	return nil
}
