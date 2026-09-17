package server

import (
	"context"
	"os"
	"path/filepath"
	"strings"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

// resolveSkillTarget maps an opaque discovered instance ID back to exactly one
// server-owned platform root. The request never supplies a platform or path,
// so a stale, missing, or ambiguous target fails closed.
func (s *Server) resolveSkillTarget(ctx context.Context, id string) (skillinstall.Target, error) {
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
	if len(matches) != 1 {
		return skillinstall.Target{}, skillinstall.ErrChanged
	}
	return matches[0], nil
}

func displayTargetRoot(path, home string) string {
	shown := filepath.ToSlash(path)
	home = strings.TrimSuffix(filepath.ToSlash(home), "/")
	if home != "" && strings.HasPrefix(shown, home+"/") {
		return "~" + strings.TrimPrefix(shown, home)
	}
	return shown
}
