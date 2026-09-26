//go:build !linux

package main

import (
	"context"
	"errors"
)

func cmdUserServiceStatus(context.Context, []string) error {
	return errors.New("user-service-status currently requires Linux")
}
