//go:build !linux

package main

import (
	"context"
	"errors"
)

func cmdUpgradeCapabilities([]string) error { return errors.New("enterprise_upgrade_requires_linux") }
func cmdApplyEnterpriseUpgrade(context.Context, []string) error {
	return errors.New("enterprise_upgrade_requires_linux")
}
func cmdRecoverEnterpriseUpgrade(context.Context, []string) error {
	return errors.New("enterprise_upgrade_requires_linux")
}
