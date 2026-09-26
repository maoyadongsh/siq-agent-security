//go:build !linux

package main

import "errors"

func cmdVerifyEnterpriseRelease([]string) error {
	return errors.New("enterprise_release_verification_requires_linux")
}
