package main

import (
	"errors"
	"siq-agent-security/apps/agentshield/internal/clientrelease"
	"siq-agent-security/apps/agentshield/internal/state"
)

type serviceBinaryCheck struct {
	bindings   state.ServiceBinaryBindings
	sourcePath string // Only fresh upgrades re-observe the historical source.
	targetPath string
}

func checkServiceBinary(path, expected string) error {
	actual, err := clientrelease.Digest(path)
	if err != nil {
		return err
	}
	if actual != expected {
		return errors.New("service-switch: binary content differs from recorded identity")
	}
	return nil
}
func (c *serviceBinaryCheck) target() error {
	if c == nil {
		return nil
	}
	return checkServiceBinary(c.targetPath, c.bindings.TargetSHA256)
}
func (c *serviceBinaryCheck) source() error {
	if c == nil || c.sourcePath == "" {
		return nil
	}
	return checkServiceBinary(c.sourcePath, c.bindings.SourceSHA256)
}
