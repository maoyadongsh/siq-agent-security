package skillmanifest

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"siq-agent-security/apps/agentshield/internal/product"
)

const goModuleLine = "module siq-agent-security/apps/agentshield"

// FindModuleRoot walks from cwd (and the executable) until it finds this
// module's go.mod.
func FindModuleRoot() (string, error) {
	var starts []string
	if cwd, err := os.Getwd(); err == nil {
		starts = append(starts, cwd)
	}
	if ex, err := os.Executable(); err == nil {
		starts = append(starts, filepath.Dir(ex))
	}
	for _, s := range starts {
		for d := s; ; d = filepath.Dir(d) {
			p := filepath.Join(d, "go.mod")
			if raw, err := os.ReadFile(p); err == nil && strings.Contains(string(raw), goModuleLine) {
				return d, nil
			}
			if filepath.Dir(d) == d {
				break
			}
		}
	}
	return "", fmt.Errorf("skillmanifest: apps/agentshield go.mod not found from cwd")
}

// FindSkillDir locates skills/siq-agent-security (SKILL.md present).
func FindSkillDir() (string, error) {
	var starts []string
	if cwd, err := os.Getwd(); err == nil {
		starts = append(starts, cwd)
	}
	if root, err := FindModuleRoot(); err == nil {
		starts = append(starts, filepath.Join(root, "..", ".."))
	}
	for _, s := range starts {
		for d := s; ; d = filepath.Dir(d) {
			p := filepath.Join(d, "skills", product.Name)
			if _, err := os.Stat(filepath.Join(p, "SKILL.md")); err == nil {
				return p, nil
			}
			if filepath.Dir(d) == d {
				break
			}
		}
	}
	return "", fmt.Errorf("skillmanifest: skills/%s not found", product.Name)
}

// RepoRoot is the parent of apps/.
func RepoRoot() (string, error) {
	mod, err := FindModuleRoot()
	if err != nil {
		return "", err
	}
	return filepath.Clean(filepath.Join(mod, "..", "..")), nil
}
