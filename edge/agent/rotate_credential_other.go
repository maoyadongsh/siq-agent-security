//go:build !linux

package main

import (
	"context"
	"errors"
)

func cmdRotateCredential(context.Context, []string) error {
	return errors.New("credential_rotation_requires_linux")
}
