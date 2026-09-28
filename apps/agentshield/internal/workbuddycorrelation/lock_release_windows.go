package workbuddycorrelation

import (
	"crypto/rand"
	"encoding/hex"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

// Never delete the reusable name on Windows: an in-progress deletion can make
// CREATE_NEW return access denied. Rename only the verified owned handle first.
func releaseOwnedLock(path string, created os.FileInfo) {
	var nonce [16]byte
	if _, err := rand.Read(nonce[:]); err != nil {
		return
	}
	retired := filepath.Join(filepath.Dir(path), "retired-lock-"+hex.EncodeToString(nonce[:]))
	moved, err := statefs.PublishPrivateNew(path, retired, created)
	if !moved || err != nil {
		return
	}
	// The publisher closed its exclusive handle before returning. Recheck
	// ownership before removing this invocation's unique, non-authoritative file.
	f, err := statefs.OpenPrivate(retired)
	if err != nil {
		return
	}
	info, statErr := f.Stat()
	closeErr := f.Close()
	if statErr == nil && closeErr == nil && os.SameFile(created, info) {
		_ = statefs.Remove(retired)
	}
}
