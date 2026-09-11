package state

import (
	"encoding/json"
	"errors"
	"path/filepath"
	"strings"
)

// DiscoveryRoots holds user-added read-only discovery scope. It is separate
// from enforcement configuration and is published as immutable versions.
type DiscoveryRoots struct {
	SchemaVersion string   `json:"schema_version"`
	ProjectDirs   []string `json:"project_dirs"`
	SkillDirs     []string `json:"skill_dirs"`
}

func (r DiscoveryRoots) valid() bool {
	if r.SchemaVersion != "local-discovery-roots/v1" || r.ProjectDirs == nil || r.SkillDirs == nil || len(r.ProjectDirs)+len(r.SkillDirs) > 16 {
		return false
	}
	for _, paths := range [][]string{r.ProjectDirs, r.SkillDirs} {
		seen := map[string]bool{}
		for _, path := range paths {
			if !filepath.IsAbs(path) || filepath.Clean(path) != path || len(path) > 4096 || strings.ContainsAny(path, "\x00\r\n") || strings.HasPrefix(path, `\\`) || strings.HasPrefix(path, "//") || seen[path] {
				return false
			}
			seen[path] = true
		}
	}
	return true
}

func (s *Store) LoadDiscoveryRoots() (DiscoveryRoots, int, error) {
	roots := DiscoveryRoots{SchemaVersion: "local-discovery-roots/v1", ProjectDirs: []string{}, SkillDirs: []string{}}
	revision, raw, err := s.LatestSeq("discovery-roots", "scope")
	if err != nil {
		return roots, revision, err
	}
	if revision >= 0 {
		var saved DiscoveryRoots
		if json.Unmarshal(raw, &saved) != nil || !saved.valid() {
			return roots, revision, errors.New("state: discovery scope unreadable")
		}
		roots = saved
	}
	return roots, revision, nil
}

func (s *Store) SaveDiscoveryRoots(roots DiscoveryRoots, expected int) error {
	if !roots.valid() {
		return errors.New("state: invalid discovery scope")
	}
	_, err := s.PutVersionedCAS("discovery-roots", "scope", expected, roots)
	return err
}
