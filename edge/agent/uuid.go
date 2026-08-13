package main

import (
	"crypto/rand"
	"fmt"
)

// NewUUID returns a random (version 4) UUID string. We deliberately avoid the
// github.com/google/uuid dependency so the whole agent builds with the
// standard library only (no go.sum / module download needed).
func NewUUID() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", fmt.Errorf("uuid: crypto/rand failed: %w", err)
	}
	b[6] = (b[6] & 0x0f) | 0x40 // version 4
	b[8] = (b[8] & 0x3f) | 0x80 // RFC 4122 variant bits
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x",
		b[0:4], b[4:6], b[6:8], b[8:10], b[10:16]), nil
}
