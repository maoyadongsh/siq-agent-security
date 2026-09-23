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

// Preparation is deliberately distinct from registration: the signed record
// can be recovered before any system manager is asked to consume the file.
func cmdServicePrepare(args []string, out io.Writer) error {
	return withPreparedUserService(args, func(_ string, record state.UserServiceRecord) error {
		return json.NewEncoder(out).Encode(record)
	})
}

func withPreparedUserService(args []string, apply func(string, state.UserServiceRecord) error) (resultErr error) {
	var unit bytes.Buffer
	if err := cmdServiceUnit(args, &unit); err != nil {
		return err
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	initialKey, err := loadUserServicePreparationKey(dir)
	if err != nil {
		return err
	}
	controlLock, err := state.AcquireScopedWriter(dir, "service-control")
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, controlLock.Release()) }()
	w, err := state.AcquireWriter(dir)
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, w.Release()) }()
	s, err := state.Open(dir)
	if err != nil {
		return err
	}
	key, err := signing.LoadExisting(dir)
	if err != nil {
		return err
	}
	if key.PublicBase64() != initialKey.PublicBase64() {
		return errors.New("service-prepare: signing identity changed during preparation")
	}
	record, err := s.PrepareUserService(w, key, unit.Bytes())
	if err != nil {
		return err
	}
	path, err := filepath.Abs(filepath.Join(dir, record.UnitName))
	if err != nil {
		return err
	}
	return apply(path, record)
}

// Our own lifecycle lock must not turn a pristine directory into apparent
// history. Establish the identity under the primary writer, then reacquire the
// normal lifecycle/primary pair and revalidate it before any signed publication.
func loadUserServicePreparationKey(dir string) (key *signing.Key, resultErr error) {
	writer, err := state.AcquireWriter(dir)
	if err != nil {
		return nil, err
	}
	defer func() { resultErr = errors.Join(resultErr, writer.Release()) }()
	return signing.Load(dir)
}
