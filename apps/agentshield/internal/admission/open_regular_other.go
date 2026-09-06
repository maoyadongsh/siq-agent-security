//go:build !unix

package admission

import "os"

// openRegular falls back to os.Open where O_NOFOLLOW/O_NONBLOCK are unavailable.
// Post-open Stat + SameFile remain mandatory; residual TOCTOU is documented in ADR-013.
func openRegular(path string) (*os.File, error) {
	return os.Open(path)
}
