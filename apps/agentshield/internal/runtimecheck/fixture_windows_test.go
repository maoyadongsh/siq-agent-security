package runtimecheck

import (
	"testing"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/runtimepath"
	"siq-agent-security/apps/agentshield/internal/state"
)

func prepareRuntimeCheckFixtureState(t *testing.T, st *state.Store) {
	t.Helper()
	w, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	_, initErr := st.Initialize(w, 47611)
	releaseErr := w.Release()
	if initErr != nil || releaseErr != nil {
		t.Fatal(initErr, releaseErr)
	}
	if _, err := st.ActivateWindowsProfile(true, "runtime-check-component-test"); err != nil {
		t.Fatal(err)
	}
}

func runtimeCheckFixtureTarget(t *testing.T, target adapterinstall.RuntimeTarget) adapterinstall.RuntimeTarget {
	t.Helper()
	facts, err := runtimepath.InspectWindows(target.ProfilePath, false)
	if err != nil {
		t.Fatal(err)
	}
	target.RootIdentityDigest, err = facts.IdentityDigest()
	if err != nil {
		t.Fatal(err)
	}
	target.FilesystemProfile = runtimeaction.FilesystemWindowsLocalDriveV1
	return target
}
