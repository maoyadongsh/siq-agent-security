// Package runtimepath verifies live filesystem facts for explicitly selected
// Windows resource authority. It neither creates authority nor executes tools.
package runtimepath

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"slices"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

var ErrUnverified = errors.New("runtime_filesystem_unverified")

type identity struct {
	volume, indexHigh, indexLow uint32
	createdHigh, createdLow     uint32
	directory                   bool
}

// Snapshot is a local, non-serializable observation. Revalidate it immediately
// before use; it cannot guarantee that a host's later path lookup is unchanged.
type Snapshot struct {
	path, device         string
	allowMissing, exists bool
	objects              []identity
}

// InspectWindows requires the caller to have already selected the Windows
// profile from verified authority. Only the final component may be absent.
func InspectWindows(path string, allowMissingLeaf bool) (*Snapshot, error) {
	canonical, err := runtimeaction.NormalizeResourceForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, "filesystem", path)
	if err != nil {
		return nil, ErrUnverified
	}
	return inspectWindows(canonical, allowMissingLeaf)
}

func (s *Snapshot) Path() string {
	if s == nil {
		return ""
	}
	return s.path
}
func (s *Snapshot) Exists() bool { return s != nil && s.exists }
func (s *Snapshot) IsDirectory() bool {
	return s != nil && s.exists && len(s.objects) > 0 && s.objects[len(s.objects)-1].directory
}

// IdentityDigest binds a signed scope to the observed name and ancestor/file
// identities. It deliberately excludes mutable contents and sizes.
func (s *Snapshot) IdentityDigest() (string, error) {
	if s == nil || len(s.objects) == 0 {
		return "", ErrUnverified
	}
	objects := make([]any, 0, len(s.objects))
	for _, o := range s.objects {
		objects = append(objects, []any{int64(o.volume), int64(o.indexHigh), int64(o.indexLow), int64(o.createdHigh), int64(o.createdLow), o.directory})
	}
	raw, err := canon.Marshal([]any{"windows-resource-identity/v1", s.path, s.device, s.exists, objects})
	if err != nil {
		return "", ErrUnverified
	}
	digest := sha256.Sum256(raw)
	return hex.EncodeToString(digest[:]), nil
}

// Revalidate rejects changed identity or existence. This is deliberately not a
// content-integrity check and does not authorize the operation or its parameters.
func (s *Snapshot) Revalidate() error {
	if s == nil || len(s.objects) == 0 {
		return ErrUnverified
	}
	next, err := InspectWindows(s.path, s.allowMissing)
	if err != nil || s.device != next.device || s.exists != next.exists || !slices.Equal(s.objects, next.objects) {
		return ErrUnverified
	}
	return nil
}
