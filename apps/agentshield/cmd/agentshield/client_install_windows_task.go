package main

import (
	"errors"
	"os/user"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func verifyInstalledWindowsClient(st *state.Store, staged string) error {
	current, err := user.Current()
	if err != nil || !state.WindowsUserSIDValid(current.Uid) {
		return errors.New("client-install: current Windows user not confirmed")
	}
	key, err := signing.LoadExisting(st.Dir)
	if err != nil {
		return err
	}
	return verifyInstalledWindowsClientTask(st, key, staged, current.Uid, runWindowsTaskQuery, runWindowsTaskRuntime)
}

// The expected action is the verified staged program, not this installer or
// the original download. Production callers always use the native readers.
func verifyInstalledWindowsClientTask(st *state.Store, key *signing.Key, staged, sid string, query func(string) ([]byte, error), runtime func(string, string) (string, error)) error {
	instance, err := st.ReadLocalInstance()
	if err != nil {
		return err
	}
	expected, err := renderWindowsTask(staged, st.Dir, instance.InstanceID, sid)
	if err != nil {
		return err
	}
	result, err := readOwnedWindowsTaskRuntime(st, key, []byte(expected), sid, query, runtime)
	if err != nil {
		return err
	}
	if result.State != "running" || result.Instances != 1 {
		return errors.New("client-install: installed Windows task is not running")
	}
	return nil
}
