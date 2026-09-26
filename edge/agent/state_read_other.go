//go:build !linux

package main

import "os"

// Enterprise descriptor-based state protection currently applies to Linux.
func readDeviceState(path string) ([]byte, error) { return os.ReadFile(path) }
