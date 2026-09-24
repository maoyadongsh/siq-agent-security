package server

import (
	"context"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
)

type AdapterInstance struct {
	ID        string                   `json:"instance_id"`
	Platform  string                   `json:"platform"`
	Name      string                   `json:"name"`
	ConfigDir string                   `json:"config_dir"`
	Source    string                   `json:"source"`
	Default   bool                     `json:"default"`
	Active    bool                     `json:"active"`
	Detected  bool                     `json:"detected"`
	Diagnosis adapterinstall.Diagnosis `json:"diagnosis"`
}

func (s *Server) hermesRoots() hermeshome.Options {
	home := s.d.Home
	if home == "" {
		home, _ = os.UserHomeDir()
	}
	roots, _, err := s.d.Store.LoadDiscoveryRoots()
	return hermeshome.Options{Home: home, Override: s.d.HermesHome, LocalAppData: s.d.LocalAppData, OS: s.d.HermesOS, ProjectDirs: roots.ProjectDirs, ProjectScopeUnavailable: err != nil}
}
func (s *Server) resolveAdapterOptions(platform, id string) (adapterinstall.Options, error) {
	opts := s.adapterOptions(platform)
	if id == "" {
		return opts, nil
	}
	if platform == adapterinstall.WorkBuddy {
		target, err := s.resolveRuntimeIdentityTarget(context.Background(), id)
		if err != nil || target.Platform != platform {
			return opts, adapterinstall.ErrPlanChanged
		}
		return adapterinstall.WithWorkBuddyInstance(opts, target.Root), nil
	}
	if platform == adapterinstall.OpenClaw {
		// OpenClaw has one default config root; a missing root or a foreign
		// instance ID must fail closed rather than fall back to defaults.
		root := adapterinstall.DefaultConfigDir(opts.Home, platform)
		if st, err := os.Stat(root); err != nil || !st.IsDir() || id != hermeshome.Identifier(root) {
			return opts, adapterinstall.ErrPlanChanged
		}
		return adapterinstall.WithOpenClawInstance(opts, root), nil
	}
	if platform != adapterinstall.Hermes {
		return opts, adapterinstall.ErrPlanChanged
	}
	root, err := hermeshome.Resolve(s.hermesRoots(), id)
	if err != nil {
		return opts, adapterinstall.ErrPlanChanged
	}
	return adapterinstall.WithHermesInstance(opts, root), nil
}
func (s *Server) adapterInstances(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	platform := r.URL.Query().Get("platform")
	includeProjects := r.URL.Query().Get("include_projects")
	if values, ok := r.URL.Query()["include_projects"]; ok && (len(values) != 1 || includeProjects != "true" || platform != adapterinstall.Hermes) {
		writeJSON(w, 400, map[string]any{"error": "invalid project discovery request"})
		return
	}
	if platform != adapterinstall.Hermes && platform != adapterinstall.OpenClaw && platform != adapterinstall.WorkBuddy {
		writeJSON(w, 400, map[string]any{"error": "instance listing requires hermes, openclaw or workbuddy"})
		return
	}
	if platform == adapterinstall.WorkBuddy {
		s.workBuddyInstanceRow(w)
		return
	}
	if platform == adapterinstall.OpenClaw {
		s.openClawInstanceRow(w, platform)
		return
	}
	roots := s.hermesRoots()
	schema := "local-adapter-instances/v1"
	if includeProjects == "true" {
		schema = "local-adapter-instances/v3"
	} else {
		roots.ProjectDirs = nil
		roots.ProjectScopeUnavailable = false
	}
	scan := hermeshome.Scan(roots)
	rows := []AdapterInstance{}
	for _, root := range scan.Roots {
		shown := filepath.ToSlash(root.Path)
		home := strings.TrimSuffix(filepath.ToSlash(roots.Home), "/")
		if strings.HasPrefix(shown, home+"/") {
			shown = "~" + strings.TrimPrefix(shown, home)
		}
		opts := adapterinstall.WithHermesInstance(s.adapterOptions(adapterinstall.Hermes), root)
		rows = append(rows, AdapterInstance{ID: root.ID, Platform: adapterinstall.Hermes, Name: root.Name, ConfigDir: shown, Source: root.Source, Default: root.Default, Active: root.Active, Detected: root.Detected, Diagnosis: s.diagnoseInstance(opts)})
	}
	writeJSON(w, 200, map[string]any{"schema_version": schema, "platform_changes": false, "native_available": adapterinstall.FindHermesCLI(s.d.HermesCLI) != "", "instances": rows, "issues": scan.Issues})
}

func (s *Server) workBuddyInstanceRow(w http.ResponseWriter) {
	rows, issues := []AdapterInstance{}, []string{}
	managed := false
	root, source, err := s.workBuddyRoot()
	if err != nil {
		issues = append(issues, "WorkBuddy 配置目录不存在或无法验证")
	} else if target, err := s.resolveRuntimeIdentityTarget(context.Background(), hermeshome.Identifier(root)); err != nil || target.Platform != adapterinstall.WorkBuddy {
		issues = append(issues, "WorkBuddy 实例目录存在歧义")
	} else {
		opts := adapterinstall.WithWorkBuddyInstance(s.adapterOptions(adapterinstall.WorkBuddy), root)
		rows = append(rows, AdapterInstance{ID: target.InstanceID, Platform: adapterinstall.WorkBuddy, Name: "default", ConfigDir: target.Display, Source: source, Default: true, Active: true, Detected: true, Diagnosis: s.diagnoseInstance(opts)})
		managed = runtime.GOOS == "windows"
	}
	writeJSON(w, 200, map[string]any{"schema_version": "local-adapter-instances/v2", "platform_changes": false, "native_available": false, "managed_runtime_available": managed, "instances": rows, "issues": issues})
}

// openClawInstanceRow lists OpenClaw's single default instance. Its config
// root is fixed, so discovery is a directory check rather than a scan; the
// instance row is reported even when the root is absent so callers can tell
// "not installed" from a bad request.
func (s *Server) openClawInstanceRow(w http.ResponseWriter, platform string) {
	home := s.d.Home
	if home == "" {
		home, _ = os.UserHomeDir()
	}
	root := adapterinstall.DefaultConfigDir(home, platform)
	shown := filepath.ToSlash(root)
	if strings.HasPrefix(shown, strings.TrimSuffix(filepath.ToSlash(home), "/")+"/") {
		shown = "~" + strings.TrimPrefix(shown, home)
	}
	rows := []AdapterInstance{}
	issues := []string{}
	if st, err := os.Stat(root); err == nil && st.IsDir() {
		opts := adapterinstall.WithOpenClawInstance(s.adapterOptions(platform), root)
		rows = append(rows, AdapterInstance{ID: hermeshome.Identifier(root), Platform: platform, Name: "default", ConfigDir: shown, Source: "default", Default: true, Active: true, Detected: true, Diagnosis: s.diagnoseInstance(opts)})
	} else {
		issues = append(issues, "OpenClaw 配置目录不存在或不可访问："+shown)
	}
	writeJSON(w, 200, map[string]any{"schema_version": "local-adapter-instances/v1", "platform_changes": false, "native_available": false, "instances": rows, "issues": issues})
}
