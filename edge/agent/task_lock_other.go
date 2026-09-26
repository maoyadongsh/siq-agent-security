//go:build !linux

package main

// Legacy one-shot command behavior is unchanged off Linux. serve rejects these
// platforms before this function; no cross-platform singleton claim is made.
func acquireTaskLock() (func(), error) { return func() {}, nil }
