package server

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/runtimepath"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

// resolveSkillTarget maps an opaque discovered instance ID back to exactly one
// server-owned platform root. The request never supplies a platform or path,
// so a stale, missing, or ambiguous target fails closed.
func (s *Server) resolveSkillTarget(ctx context.Context, id string) (skillinstall.Target, error) {
	target, err := s.resolveRuntimeIdentityTarget(ctx, id)
	if err != nil || target.Platform == adapterinstall.WorkBuddy {
		return skillinstall.Target{}, skillinstall.ErrChanged
	}
	return target, nil
}

// WorkBuddy is an identity target only. It does not silently become a supported
// Skill installation target. All product roots participate in ambiguity checks.
func (s *Server) resolveRuntimeIdentityTarget(ctx context.Context, id string) (skillinstall.Target, error) {
	if err := ctx.Err(); err != nil {
		return skillinstall.Target{}, err
	}
	var matches []skillinstall.Target
	hermesOptions := s.hermesRoots()
	if root, err := hermeshome.Resolve(hermesOptions, id); err == nil && root.Detected {
		matches = append(matches, skillinstall.Target{
			InstanceID: root.ID,
			Platform:   adapterinstall.Hermes,
			Root:       root.Path,
			Display:    displayTargetRoot(root.Path, hermesOptions.Home),
		})
	}
	home := s.d.Home
	if home == "" {
		home, _ = os.UserHomeDir()
	}
	openClawRoot := adapterinstall.DefaultConfigDir(home, adapterinstall.OpenClaw)
	if info, err := os.Lstat(openClawRoot); err == nil && info.IsDir() && info.Mode()&os.ModeSymlink == 0 && hermeshome.Identifier(openClawRoot) == id {
		matches = append(matches, skillinstall.Target{
			InstanceID: id,
			Platform:   adapterinstall.OpenClaw,
			Root:       openClawRoot,
			Display:    displayTargetRoot(openClawRoot, home),
		})
	}
	if root, _, err := s.workBuddyRoot(); err == nil && hermeshome.Identifier(root) == id {
		matches = append(matches, skillinstall.Target{InstanceID: id, Platform: adapterinstall.WorkBuddy, Root: root, Display: displayTargetRoot(root, home)})
	}
	if len(matches) != 1 {
		return skillinstall.Target{}, skillinstall.ErrChanged
	}
	return matches[0], nil
}

// Preserve the configured spelling until the native path checker has rejected
// aliases; filepath.Clean must not hide a rejected drive/path interpretation.
func (s *Server) workBuddyRoot() (string, string, error) {
	home := s.d.Home
	if home == "" {
		home, _ = os.UserHomeDir()
	}
	root, source := filepath.Join(home, ".workbuddy"), "default_directory"
	if configured := os.Getenv("WORKBUDDY_CONFIG_DIR"); configured != "" {
		root, source = configured, "environment"
	}
	if !filepath.IsAbs(root) {
		return "", source, skillinstall.ErrChanged
	}
	if runtime.GOOS == "windows" {
		snapshot, err := runtimepath.InspectWindows(root, false)
		if err != nil || !snapshot.IsDirectory() {
			return "", source, skillinstall.ErrChanged
		}
	} else if info, err := os.Lstat(root); err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return "", source, skillinstall.ErrChanged
	}
	return root, source, nil
}

func displayTargetRoot(path, home string) string {
	shown := filepath.ToSlash(path)
	home = strings.TrimSuffix(filepath.ToSlash(home), "/")
	if home != "" && strings.HasPrefix(shown, home+"/") {
		return "~" + strings.TrimPrefix(shown, home)
	}
	return shown
}
