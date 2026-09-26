//go:build !linux

package main

import (
	"context"
	"errors"
)

func cmdSetupEnterprise(ctx context.Context, args []string) error {
	return errors.New("enterprise_setup_requires_linux")
}
