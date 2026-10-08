//go:build !linux

package main

import (
	"context"
	"errors"
)

func cmdReviewEnterpriseUpgrade(context.Context, []string) error {
	return errors.New("enterprise_upgrade_requires_linux")
}
