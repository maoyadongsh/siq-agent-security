//go:build !linux

package main

import (
	"context"
	"errors"
)

func cmdRecoverRegistration(ctx context.Context, args []string) error {
	return errors.New("registration_recovery_requires_linux")
}
