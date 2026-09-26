//go:build !linux

package main

// Non-Linux callers retain exclusive pending-file protection. Crash durability
// of the directory is only promised by the enterprise Linux implementation.
func syncRegistrationDirectory(dir string) error { return nil }
