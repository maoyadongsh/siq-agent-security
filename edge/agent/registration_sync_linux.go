//go:build linux

package main

import "os"

func syncRegistrationDirectory(dir string) error {
	f, err := os.Open(dir)
	if err != nil {
		return errRegistrationPending
	}
	defer f.Close()
	if f.Sync() != nil {
		return errRegistrationPending
	}
	return nil
}
