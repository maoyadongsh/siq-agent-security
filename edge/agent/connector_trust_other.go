//go:build !linux

package main

import (
	"context"
	"os"
	"os/exec"
)

func connectorCommand(ctx context.Context, path, name, digest string) (*exec.Cmd, *os.File, error) {
	if digest != "" {
		return nil, nil, ErrConnectorTrust
	}
	return exec.CommandContext(ctx, path, "--serve"), nil, nil
}

func resolveManagedConnector(state *State, name string) (string, string, error) {
	return "", "", ErrConnectorTrust
}
