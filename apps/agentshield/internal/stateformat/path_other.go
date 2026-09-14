//go:build !windows

package stateformat

// ValidatePath preserves non-Windows path spelling and the caller's rules.
func ValidatePath(string) error { return nil }
