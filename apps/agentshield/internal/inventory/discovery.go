package inventory

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const maxDiscoveryConfig = 1 << 20
const maxDiscoveryDirs = 4096
const maxDiscoveryDepth = 8

// Relationship is a configuration-level association, never an authorization
// or a claim that a particular execution used this Skill.
type Relationship struct {
	RelationshipID string   `json:"relationship_id"`
	SourceID       string   `json:"source_id"`
	SkillID        string   `json:"skill_id"`
	Basis          string   `json:"basis"`
	State          string   `json:"state"`
	EvidenceIDs    []string `json:"evidence_ids"`
}

type rootOwner struct{ id, basis string }
type workspaceRoot struct{ dir, owner string }

// SkillLocation normalizes the legacy platform prefix without changing path
// identity. It is also used when projecting immutable pre-migration records.
func SkillLocation(locator string) string {
	_, path, ok := strings.Cut(locator, "://skills/")
	if !ok || path == "" {
		return ""
	}
	return filepath.ToSlash(filepath.Clean(path))
}

func InstallationID(locator string) string {
	sum := sha256.Sum256([]byte(SkillLocation(locator)))
	return "skill-installation:" + hex.EncodeToString(sum[:])[:32]
}

func (r *run) safePath(path string) error {
	path = filepath.Clean(path)
	home := filepath.Clean(r.opts.Home)
	for current := path; ; current = filepath.Dir(current) {
		info, err := os.Lstat(current)
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return errors.New("symlink refused")
		}
		parent := filepath.Dir(current)
		// Home is the explicit scan anchor; do not reject OS-managed aliases
		// above it, such as /var on macOS. User-controlled children are checked.
		if current == home || parent == current {
			return nil
		}
	}
}

func (r *run) readConfig(path string) ([]byte, error) {
	if err := r.safePath(path); err != nil {
		return nil, err
	}
	before, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !before.Mode().IsRegular() || before.Size() > maxDiscoveryConfig {
		return nil, errors.New("config type or size refused")
	}
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > maxDiscoveryConfig {
		return nil, errors.New("config type or size refused")
	}
	raw, err := io.ReadAll(io.LimitReader(f, maxDiscoveryConfig+1))
	if err != nil || len(raw) > maxDiscoveryConfig {
		return nil, errors.New("config unreadable or too large")
	}
	return raw, nil
}

func (r *run) configuredDirectory(value string) (string, bool) {
	if value == "" || len(value) > 4096 || strings.ContainsAny(value, "\x00\r\n") || strings.HasPrefix(value, "//") || strings.HasPrefix(value, `\\`) {
		return "", false
	}
	if value == "~" {
		value = r.opts.Home
	} else if strings.HasPrefix(value, "~/") || strings.HasPrefix(value, `~\`) {
		value = filepath.Join(r.opts.Home, value[2:])
	}
	if !filepath.IsAbs(value) {
		return "", false
	}
	return filepath.Clean(value), true
}

func (r *run) walkSkills(p platformSpec, dir string, seen map[string]bool, depth int) bool {
	if err := r.safePath(dir); err != nil {
		if !os.IsNotExist(err) {
			r.report.Skipped = append(r.report.Skipped, "unreadable:"+p.name+":"+redactHome(dir, r.opts.Home))
		}
		return false
	}
	info, err := os.Lstat(dir)
	if err != nil || !info.IsDir() {
		r.report.Skipped = append(r.report.Skipped, "unreadable:"+p.name+":"+redactHome(dir, r.opts.Home))
		return false
	}
	if r.dirsVisited >= maxDiscoveryDirs || depth > maxDiscoveryDepth {
		r.report.Skipped = append(r.report.Skipped, "limit:"+p.name+":"+redactHome(dir, r.opts.Home))
		return false
	}
	if _, ok := r.skillIDs[dir]; ok {
		return true
	}
	if seen[dir] {
		return false
	}
	seen[dir] = true
	r.dirsVisited++
	if info, err := os.Lstat(filepath.Join(dir, "SKILL.md")); err == nil {
		if !info.Mode().IsRegular() {
			r.report.Skipped = append(r.report.Skipped, "unhashable:"+p.name+":"+redactHome(dir, r.opts.Home))
			return false
		}
		r.skill(p, dir, filepath.Base(dir))
		_, ok := r.skillIDs[dir]
		return ok
	}
	f, err := os.Open(dir)
	if err != nil {
		r.report.Skipped = append(r.report.Skipped, "unreadable:"+p.name+":"+redactHome(dir, r.opts.Home))
		return false
	}
	entries, err := f.ReadDir(maxDiscoveryDirs + 1)
	_ = f.Close()
	if err != nil && err != io.EOF {
		r.report.Skipped = append(r.report.Skipped, "unreadable:"+p.name+":"+redactHome(dir, r.opts.Home))
		return false
	}
	if len(entries) > maxDiscoveryDirs {
		r.report.Skipped = append(r.report.Skipped, "limit:"+p.name+":"+redactHome(dir, r.opts.Home))
		entries = entries[:maxDiscoveryDirs]
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].Name() < entries[j].Name() })
	found := false
	for _, entry := range entries {
		if entry.Type()&os.ModeSymlink != 0 {
			r.report.Skipped = append(r.report.Skipped, "symlink:"+p.name+":"+redactHome(filepath.Join(dir, entry.Name()), r.opts.Home))
			continue
		}
		if !entry.IsDir() || strings.HasPrefix(entry.Name(), ".") || entry.Name() == "node_modules" {
			continue
		}
		if r.walkSkills(p, filepath.Join(dir, entry.Name()), seen, depth+1) {
			found = true
		}
	}
	return found
}

func (r *run) platformOwners(platform string) []string {
	var owners []string
	for _, candidate := range r.report.Candidates {
		if platform == "hermes" && candidate.CandidateID == "agent:hermes:default" ||
			platform == "openclaw" && candidate.SourceType == "openclaw_agent" {
			owners = append(owners, candidate.CandidateID)
		}
	}
	if len(owners) == 0 {
		for _, candidate := range r.report.Candidates {
			if candidate.CandidateID == "platform:"+platform {
				owners = append(owners, candidate.CandidateID)
			}
		}
	}
	return owners
}

func (r *run) addRootOwners(root string, ids []string, basis string) {
	root = filepath.Clean(root)
	for _, id := range ids {
		r.rootOwners[root] = append(r.rootOwners[root], rootOwner{id, basis})
	}
}

func (r *run) buildRelationships() {
	byID := map[string]Candidate{}
	for _, candidate := range r.report.Candidates {
		byID[candidate.CandidateID] = candidate
	}
	seen := map[string]bool{}
	for root, owners := range r.rootOwners {
		for path, skillID := range r.skillIDs {
			rel, err := filepath.Rel(root, path)
			if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
				continue
			}
			for _, owner := range owners {
				source, ok := byID[owner.id]
				if !ok {
					continue
				}
				key := owner.id + "|" + skillID + "|" + owner.basis
				if seen[key] {
					continue
				}
				seen[key] = true
				evidence := append([]string{}, source.EvidenceIDs...)
				for _, id := range byID[skillID].EvidenceIDs {
					if !containsStr(evidence, id) {
						evidence = append(evidence, id)
					}
				}
				sort.Strings(evidence)
				sum := sha256.Sum256([]byte(key))
				r.report.Relationships = append(r.report.Relationships, Relationship{
					RelationshipID: "rel-" + hex.EncodeToString(sum[:])[:32], SourceID: owner.id, SkillID: skillID,
					Basis: owner.basis, State: "inferred", EvidenceIDs: evidence,
				})
			}
		}
	}
	sort.Slice(r.report.Relationships, func(i, j int) bool {
		return r.report.Relationships[i].RelationshipID < r.report.Relationships[j].RelationshipID
	})
}
