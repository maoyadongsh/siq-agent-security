package inventory

import (
	"errors"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"sort"
)

type ScanRoot struct {
	Path     string `json:"path"`
	Kind     string `json:"kind"`
	Platform string `json:"platform"`
	Status   string `json:"status"`
}

// NormalizeDirectory validates an explicitly selected local directory, without
// shell expansion, environment substitution, network access or creation.
func NormalizeDirectory(home, input string) (string, error) {
	r := &run{opts: Options{Home: home}}
	path, ok := r.configuredDirectory(input)
	if !ok {
		return "", errors.New("请输入本地绝对目录或 ~/ 开头的目录")
	}
	if err := r.safePath(path); err != nil {
		return "", errors.New("目录不存在、不可读取或包含符号链接")
	}
	info, err := os.Stat(path)
	if err != nil || !info.IsDir() {
		return "", errors.New("所选路径不是可读取的目录")
	}
	return path, nil
}

// Preview lists the same known roots as Run. It reads only the small OpenClaw
// config needed to enumerate explicitly declared workspace roots, never Skills.
func Preview(opts Options) []ScanRoot {
	var out []ScanRoot
	seen := map[string]bool{}
	r := &run{opts: opts, report: &Report{}, skillIDs: map[string]string{}, rootOwners: map[string][]rootOwner{}}
	add := func(path, kind, platform string) {
		key := path + "|" + kind
		if seen[key] {
			return
		}
		seen[key] = true
		status := "available"
		if err := r.safePath(path); err != nil {
			status = "unreadable"
			if os.IsNotExist(err) {
				status = "missing"
			}
		} else if info, err := os.Lstat(path); err != nil || (kind == "platform_config" || kind == "mcp_config") && !info.Mode().IsRegular() ||
			(kind == "skill_directory" || kind == "profile_directory") && !info.IsDir() {
			status = "unreadable"
		}
		out = append(out, ScanRoot{Path: redactHome(path, opts.Home), Kind: kind, Platform: platform, Status: status})
	}
	for _, p := range platforms {
		if p.name == "hermes" {
			continue
		}
		for _, config := range p.configs {
			add(filepath.Join(opts.Home, config), "platform_config", p.name)
		}
		for _, dir := range p.skillDirs {
			add(filepath.Join(opts.Home, dir), "skill_directory", p.name)
		}
		for _, project := range opts.ProjectDirs {
			for _, dir := range p.projectDir {
				add(filepath.Join(project, dir), "skill_directory", p.name)
			}
		}
	}
	for _, root := range hermeshome.Scan(hermeshome.Options{Home: opts.Home, Override: opts.HermesHome, LocalAppData: opts.LocalAppData}).Roots {
		add(filepath.Join(root.Path, "config.yaml"), "platform_config", "hermes")
		add(filepath.Join(root.Path, "skills"), "skill_directory", "hermes")
		if root.Source == "named_profile" {
			add(root.Path, "profile_directory", "hermes")
		} else {
			add(filepath.Join(root.Path, "profiles"), "profile_directory", "hermes")
		}
	}
	for _, config := range mcpConfigs {
		add(filepath.Join(opts.Home, config.rel), "mcp_config", config.client)
	}
	for _, dir := range opts.SkillDirs {
		add(dir, "skill_directory", "unknown")
	}
	if raw, err := r.readConfig(filepath.Join(opts.Home, ".openclaw", "openclaw.json")); err == nil {
		// The preview needs only workspace paths; a config evidence ID prevents
		// signing fallback and no candidate is returned by this function.
		r.openclawAgents(raw, "preview")
		for _, root := range r.workspaceRoots {
			add(root.dir, "skill_directory", "openclaw")
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Path != out[j].Path {
			return out[i].Path < out[j].Path
		}
		return out[i].Kind < out[j].Kind
	})
	return out
}
