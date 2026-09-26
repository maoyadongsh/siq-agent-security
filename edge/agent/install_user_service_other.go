//go:build !linux

package main

import (
	"context"
	"errors"
)

func cmdInstallUserService(ctx context.Context, args []string) error {
	return errors.New("user_service_install_requires_linux")
}
