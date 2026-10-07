package skillcontext

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"path"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

// NativeInstallMount is supplied by the trusted launcher, never tool input.
// Both roots and the exact approved Claim are fixed for a running candidate.
type NativeInstallMount struct {
	InstanceID, InstallID, ClaimSignature, HostRoot, RuntimeRoot string
}
type NativeInstallResolver struct {
	installs    *skillinstall.Store
	mounts      map[string]NativeInstallMount
	verifyMount func(context.Context, Subject, NativeInstallMount) error
}

func nativePathSHA(path string) string {
	b := sha256.Sum256([]byte(path))
	return hex.EncodeToString(b[:])
}
func NewNativeInstallResolver(installs *skillinstall.Store, mounts []NativeInstallMount, verifyMount func(context.Context, Subject, NativeInstallMount) error) (*NativeInstallResolver, error) {
	if installs == nil || verifyMount == nil || len(mounts) == 0 || len(mounts) > 64 {
		return nil, hostError()
	}
	r := &NativeInstallResolver{installs: installs, mounts: map[string]NativeInstallMount{}, verifyMount: verifyMount}
	for _, m := range mounts {
		if !instancePattern.MatchString(m.InstanceID) || !hex128Pattern.MatchString(m.ClaimSignature) || !skillinstall.ValidNativeRoot(m.RuntimeRoot) || !filepath.IsAbs(m.HostRoot) || filepath.Clean(m.HostRoot) != m.HostRoot || m.InstallID == "" {
			return nil, hostError()
		}
		for _, old := range r.mounts {
			if old.InstanceID == m.InstanceID && (old.RuntimeRoot == m.RuntimeRoot || strings.HasPrefix(old.RuntimeRoot, m.RuntimeRoot+"/") || strings.HasPrefix(m.RuntimeRoot, old.RuntimeRoot+"/")) {
				return nil, hostError()
			}
		}
		key := m.InstanceID + ":" + nativePathSHA(path.Join(m.RuntimeRoot, "SKILL.md"))
		r.mounts[key] = m
	}
	return r, nil
}
func (r *NativeInstallResolver) Resolve(subject Subject, source NativeSource) (InstallRef, error) {
	if r == nil || !validNativeSubject(subject, true) || subject.Platform != "hermes" || !source.valid() {
		return InstallRef{}, hostError()
	}
	m, ok := r.mounts[subject.InstanceID+":"+source.SkillFile.PathSHA256]
	if !ok {
		return InstallRef{}, hostError()
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if r.verifyMount(ctx, subject, m) != nil {
		return InstallRef{}, hostError()
	}
	snapshot, err := r.installs.ReadNativeSource(ctx, m.InstallID, m.InstanceID, m.RuntimeRoot, source.ContentFile.PathSHA256)
	if err != nil || snapshot.ClaimSignature != m.ClaimSignature || snapshot.HostRoot != m.HostRoot || snapshot.InstanceID != subject.InstanceID {
		return InstallRef{}, hostError()
	}
	same := func(a NativeSourceFile, b skillinstall.NativeSourceFile) bool {
		return a.PathSHA256 == b.PathSHA256 && a.SHA256 == b.SHA256 && a.Bytes == b.Bytes
	}
	if !same(source.SkillFile, snapshot.Main) || !same(source.ContentFile, snapshot.Content) || source.TextSHA256 != snapshot.TextSHA256 || r.verifyMount(ctx, subject, m) != nil || ctx.Err() != nil {
		return InstallRef{}, hostError()
	}
	return InstallRef{InstallID: snapshot.InstallID, ClaimSignature: snapshot.ClaimSignature}, nil
}
