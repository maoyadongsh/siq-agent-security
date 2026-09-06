//go:build !unix

package main

import "os"

// openRegular on non-unix builds falls back to os.Open; symlink refusal is
// covered by symlinkEscapes on the collect path where applicable.
func openRegular(path string) (*os.File, error) {
	return os.Open(path)
}
