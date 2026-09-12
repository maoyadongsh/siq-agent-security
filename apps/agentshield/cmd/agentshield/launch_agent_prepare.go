package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func cmdLaunchAgentPrepare(args []string, out io.Writer) error {
	return withPreparedLaunchAgent(args, func(_ *state.Store, _ *signing.Key, _ []byte, record state.LaunchAgentRecord) error {
		return json.NewEncoder(out).Encode(record)
	})
}
func withPreparedLaunchAgent(args []string, apply func(*state.Store, *signing.Key, []byte, state.LaunchAgentRecord) error) (resultErr error) {
	var plist bytes.Buffer
	if err := cmdLaunchAgentPlist(args, &plist); err != nil {
		return err
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	lifecycle, err := state.AcquireWriter(filepath.Join(dir, "service-control"))
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, lifecycle.Release()) }()
	writer, err := state.AcquireWriter(dir)
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, writer.Release()) }()
	st, err := state.Open(dir)
	if err != nil {
		return err
	}
	key, err := signing.Load(dir)
	if err != nil {
		return err
	}
	record, err := st.PrepareLaunchAgent(writer, key, plist.Bytes())
	if err != nil {
		return err
	}
	return apply(st, key, plist.Bytes(), record)
}
