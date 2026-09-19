package main

import (
	"errors"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

// A fresh init deliberately has only installation metadata. Establish its
// signing identity before activation publishes immutable history; afterwards
// the missing-identity guard must require restoration, never generate a key.
func prepareWindowsProfileIdentity(dir string) (resultErr error) {
	if runtime.GOOS != "windows" {
		return nil // The activation command retains its platform refusal.
	}
	if _, err := state.CheckStateCompatibility(dir); err != nil {
		if errors.Is(err, stateformat.ErrWindowsProfileMigration) {
			// Only the explicit activation recovery may read through its active
			// barrier. It validates the entire original plan; this path does not
			// read or create a key, even when the old identity has been lost.
			return nil
		}
		return err
	}
	marker, err := stateformat.ReadMarker(dir)
	if err != nil || marker.Schema != "state-format/v2" || marker.MinReader != marker.MinWriter || (marker.MinReader != 2 && marker.MinReader != 3) {
		return state.ErrWindowsProfileActivation
	}
	w, err := state.AcquireWriter(dir)
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, w.Release()) }()
	// AcquireWriter repeats compatibility validation after obtaining ownership.
	// Load preserves its existing ACL, corruption, and historical-key-loss
	// refusals; activation never treats its journal as bootstrap metadata.
	_, err = signing.Load(dir)
	return err
}
