//go:build !unix

package main

import "os"

// openRegular on non-unix builds falls back to os.Open; symlink refusal is
// best-effort via post-open Mode check in readFileLimited.
func openRegular(path string) (*os.File, error) {
	return os.Open(path)
}
