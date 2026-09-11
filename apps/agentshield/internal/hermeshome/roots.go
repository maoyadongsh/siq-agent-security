// Package hermeshome resolves profile directories without executing the host.
package hermeshome

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"unicode/utf8"
)

const MaxProfiles = 64

type Options struct{ Home, Override, LocalAppData, OS string }
type Root struct {
	ID, Name, Path, CandidateID, Source string
	Default, Active, Detected           bool
}
type Result struct {
	Roots  []Root
	Issues []string
}

func Identifier(path string) string {
	normalized := filepath.ToSlash(filepath.Clean(path))
	if runtime.GOOS == "windows" {
		normalized = strings.ToLower(normalized)
	}
	hash := sha256.Sum256([]byte(normalized))
	return "hi-" + hex.EncodeToString(hash[:16])
}
func LegacyRoot(home string) string { return filepath.Join(home, ".hermes") }

func Scan(o Options) Result {
	result := Result{Roots: []Root{}, Issues: []string{}}
	if o.Home == "" {
		o.Home, _ = os.UserHomeDir()
	}
	if o.OS == "" {
		o.OS = runtime.GOOS
	}
	base := LegacyRoot(o.Home)
	if o.OS == "windows" {
		app := o.LocalAppData
		if app == "" {
			app = filepath.Join(o.Home, "AppData", "Local")
		}
		base = filepath.Join(app, "hermes")
	}
	active := base
	roots := []string{base}
	if o.OS == "windows" && base != LegacyRoot(o.Home) {
		roots = append(roots, LegacyRoot(o.Home))
	}
	if o.Override != "" {
		if !filepath.IsAbs(o.Override) || !utf8.ValidString(o.Override) {
			result.Issues = append(result.Issues, "invalid_hermes_home")
			return result
		} else {
			active = filepath.Clean(o.Override)
			if err := safe(o.Home, active); err != nil {
				result.Issues = append(result.Issues, "unsafe_hermes_home")
				return result
			}
			custom := active
			if filepath.Base(filepath.Dir(custom)) == "profiles" {
				custom = filepath.Dir(filepath.Dir(custom))
			}
			if !contains(roots, custom) {
				roots = append(roots, custom)
			}
		}
	}
	seen := map[string]bool{}
	add := func(path, name, source string, isDefault bool) {
		path = filepath.Clean(path)
		if seen[Identifier(path)] {
			return
		}
		seen[Identifier(path)] = true
		if err := safe(o.Home, path); err != nil {
			result.Issues = append(result.Issues, "unsafe_profile_root")
			return
		}
		info, err := os.Lstat(path)
		if err != nil && !os.IsNotExist(err) || err == nil && !info.IsDir() {
			result.Issues = append(result.Issues, "unreadable_profile_root")
			return
		}
		id := Identifier(path)
		candidate := "agent:hermes:root:" + strings.TrimPrefix(id, "hi-")
		legacy := LegacyRoot(o.Home)
		if path == legacy {
			candidate = "agent:hermes:default"
		} else if filepath.Dir(path) == filepath.Join(legacy, "profiles") {
			candidate = "agent:hermes:" + filepath.Base(path)
		}
		result.Roots = append(result.Roots, Root{ID: id, Name: name, Path: path, CandidateID: candidate, Source: source, Default: isDefault, Active: path == active, Detected: err == nil})
	}
	for _, root := range roots {
		source := "default_directory"
		name := "default"
		if root != base && root != LegacyRoot(o.Home) {
			source = "environment"
			name = filepath.Base(root)
		}
		add(root, name, source, root == base)
		profiles := filepath.Join(root, "profiles")
		if err := safe(o.Home, profiles); err != nil {
			result.Issues = append(result.Issues, "unsafe_profiles_directory")
			continue
		}
		file, err := os.Open(profiles)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			result.Issues = append(result.Issues, "unreadable_profiles_directory")
			continue
		}
		entries, err := file.ReadDir(MaxProfiles + 1)
		_ = file.Close()
		if err != nil && err != io.EOF {
			result.Issues = append(result.Issues, "unreadable_profiles_directory")
			continue
		}
		if len(entries) > MaxProfiles {
			result.Issues = append(result.Issues, "profile_limit")
			entries = entries[:MaxProfiles]
		}
		sort.Slice(entries, func(i, j int) bool { return entries[i].Name() < entries[j].Name() })
		for _, entry := range entries {
			if entry.Type()&os.ModeSymlink != 0 {
				result.Issues = append(result.Issues, "symlink_profile")
				continue
			}
			if !entry.IsDir() || strings.HasPrefix(entry.Name(), ".") {
				continue
			}
			path := filepath.Join(profiles, entry.Name())
			recognized := false
			for _, marker := range []string{"config.yaml", "SOUL.md"} {
				info, err := os.Lstat(filepath.Join(path, marker))
				recognized = recognized || err == nil && info.Mode().IsRegular()
			}
			if recognized {
				add(path, entry.Name(), "named_profile", false)
			}
		}
	}
	sort.SliceStable(result.Roots, func(i, j int) bool {
		if result.Roots[i].Default != result.Roots[j].Default {
			return result.Roots[i].Default
		}
		return result.Roots[i].Path < result.Roots[j].Path
	})
	return result
}

func Resolve(o Options, id string) (Root, error) {
	for _, root := range Scan(o).Roots {
		if root.ID == id {
			return root, nil
		}
	}
	return Root{}, errors.New("hermes: instance unavailable; discover again")
}
func contains(paths []string, path string) bool {
	for _, item := range paths {
		if item == path {
			return true
		}
	}
	return false
}
func safe(home, path string) error {
	if !filepath.IsAbs(path) || !utf8.ValidString(path) {
		return errors.New("absolute root required")
	}
	for current := filepath.Clean(path); ; current = filepath.Dir(current) {
		info, err := os.Lstat(current)
		if err != nil && !os.IsNotExist(err) {
			return err
		}
		if err == nil && (!info.IsDir() || info.Mode()&os.ModeSymlink != 0) {
			return errors.New("unsafe root")
		}
		if current == filepath.Clean(home) || filepath.Dir(current) == current {
			return nil
		}
	}
}
