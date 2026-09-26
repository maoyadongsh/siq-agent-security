//go:build linux

package main

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

const supportsSkillCollection = true

func skillOpenAt(parent *os.File, name string, directory bool) (*os.File, error) {
	flags := syscall.O_RDONLY | syscall.O_NOFOLLOW | syscall.O_CLOEXEC | syscall.O_NONBLOCK
	if directory {
		flags |= syscall.O_DIRECTORY
	}
	fd, err := syscall.Openat(int(parent.Fd()), name, flags, 0)
	if err != nil {
		return nil, err
	}
	return os.NewFile(uintptr(fd), name), nil
}

func skillRoot(path string) (*os.File, error) {
	current, err := os.Open("/")
	if err != nil {
		return nil, err
	}
	for _, part := range strings.Split(strings.TrimPrefix(path, "/"), "/") {
		next, err := skillOpenAt(current, part, true)
		current.Close()
		if err != nil {
			return nil, err
		}
		current = next
	}
	return current, nil
}

func collectSkills(plan protocol.ScanPlan) (protocol.SkillCollection, error) {
	return collectSkillsVersion(plan, false)
}

func collectSkillsVersion(plan protocol.ScanPlan, ancestry bool) (protocol.SkillCollection, error) {
	result := protocol.SkillCollection{SchemaVersion: "enterprise-skill-collection/v1",
		Observations: []protocol.SkillObservation{}, Issues: []protocol.SkillCollectionIssue{}}
	if ancestry {
		result.SchemaVersion = "enterprise-skill-collection/v2"
	}
	scope := plan.Scope
	if scope == nil || len(scope.Roots) == 0 || len(scope.Roots) > 16 || len(scope.Include) != 1 || scope.Include[0] != "SKILL.md" || len(scope.Exclude) != 0 {
		return result, errors.New("explicit skill scope required")
	}
	if err := protocol.ValidateScopeSafety(scope); err != nil {
		return result, errors.New("invalid skill scope")
	}
	roots := make([]string, 0, len(scope.Roots))
	for _, root := range scope.Roots {
		root = protocol.ExpandHome(root)
		if !filepath.IsAbs(root) || strings.ContainsAny(root, "*?[") {
			return result, errors.New("literal absolute skill roots required")
		}
		roots = append(roots, filepath.Clean(root))
	}
	sort.Strings(roots)
	maxFiles := plan.Limits.MaxFiles
	if maxFiles <= 0 || maxFiles > 200 {
		maxFiles = 200
	}
	remaining := plan.Limits.MaxBytes
	if remaining <= 0 || remaining > 16*1024*1024 {
		remaining = 16 * 1024 * 1024
	}
	timeout := opTimeout
	if timeout <= 0 {
		timeout = 60 * time.Second
	}
	deadline := time.Now().Add(timeout)
	visited, manifests := 0, int64(0)
	seen := map[string]bool{}
	issue := func(path, status string) {
		result.Truncated = true
		if len(result.Issues) < 200 {
			result.Issues = append(result.Issues, protocol.SkillCollectionIssue{LocatorSHA256: protocol.ContentHash([]byte(path)), Status: status})
		}
	}
	var walk func(*os.File, string, int, []string)
	walk = func(dir *os.File, path string, depth int, parents []string) {
		if seen[path] {
			return
		}
		seen[path] = true
		if depth > 32 {
			issue(path, "depth_limit")
			return
		}
		var ancestors []string
		if ancestry {
			ancestors = append([]string{protocol.ContentHash([]byte(path))}, parents...)
		}
		for {
			if visited >= 10000 || manifests >= maxFiles || time.Now().After(deadline) {
				issue(path, "scan_limit")
				return
			}
			names, err := dir.Readdirnames(64)
			if err != nil && err != io.EOF {
				issue(path, "unreadable")
				return
			}
			for _, name := range names {
				if visited >= 10000 || manifests >= maxFiles || time.Now().After(deadline) {
					issue(path, "scan_limit")
					return
				}
				visited++
				childPath := filepath.Join(path, name)
				if name == "SKILL.md" {
					manifests++
					file, err := skillOpenAt(dir, name, false)
					if err != nil {
						issue(path, "unreadable")
						continue
					}
					before, err := file.Stat()
					if err != nil || !before.Mode().IsRegular() {
						file.Close()
						issue(path, "not_regular")
						continue
					}
					if before.Size() > protocol.MaxSkillManifestBytes || before.Size() > remaining {
						file.Close()
						issue(path, "size_limit")
						continue
					}
					limit := min(remaining, int64(protocol.MaxSkillManifestBytes))
					data, readErr := io.ReadAll(io.LimitReader(file, limit))
					after, statErr := file.Stat()
					file.Close()
					remaining -= int64(len(data))
					if readErr != nil || statErr != nil || int64(len(data)) != before.Size() || after.Size() != before.Size() || !after.ModTime().Equal(before.ModTime()) {
						issue(path, "changed_or_unreadable")
						continue
					}
					parsed := protocol.ParseSkillManifest(data)
					result.Observations = append(result.Observations, protocol.SkillObservation{
						AncestorSHA256: ancestors,
						LocatorSHA256:  protocol.ContentHash([]byte(path)), ManifestSHA256: parsed.ContentSHA256,
						ParserVersion: "enterprise-skill-manifest/v1", ParseStatus: parsed.Status,
						Name: parsed.Name, AllowedToolsPresent: parsed.AllowedToolsPresent, DeclaredTools: parsed.DeclaredTools,
						ObservedAt: time.Now().UTC().Format(time.RFC3339Nano),
					})
					continue
				}
				if strings.HasPrefix(name, ".") || name == "node_modules" || name == "vendor" {
					continue
				}
				child, err := skillOpenAt(dir, name, true)
				if err != nil {
					if !errors.Is(err, syscall.ENOTDIR) {
						issue(childPath, "unreadable_directory")
					}
					continue
				}
				walk(child, childPath, depth+1, ancestors)
				child.Close()
			}
			if err == io.EOF {
				return
			}
		}
	}
	for _, root := range roots {
		dir, err := skillRoot(root)
		if err != nil {
			issue(root, "unreadable_root")
			continue
		}
		walk(dir, root, 0, nil)
		dir.Close()
	}
	sort.Slice(result.Observations, func(i, j int) bool {
		return result.Observations[i].LocatorSHA256 < result.Observations[j].LocatorSHA256
	})
	return result, nil
}
