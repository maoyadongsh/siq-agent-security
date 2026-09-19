package server

import (
	"context"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

type skillInstallTargetView struct {
	TargetID          string  `json:"target_id"`
	InstanceID        string  `json:"instance_id"`
	Platform          string  `json:"platform"`
	Scope             string  `json:"scope"`
	RootDisplay       string  `json:"root_display"`
	TargetDisplay     string  `json:"target_display"`
	FilesystemProfile string  `json:"filesystem_profile"`
	Available         bool    `json:"available"`
	ErrorCode         *string `json:"error_code"`
}

type skillInstallTargetsView struct {
	SchemaVersion   string                   `json:"schema_version"`
	InstanceID      string                   `json:"instance_id"`
	Targets         []skillInstallTargetView `json:"targets"`
	PlatformChanges bool                     `json:"platform_changes"`
}

func (s *Server) skillInstallationTargets(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	query, queryErr := url.ParseQuery(r.URL.RawQuery)
	ids := query["instance_id"]
	if queryErr != nil || len(query) != 1 || len(ids) != 1 {
		skillInstallError(w, skillinstall.ErrInvalid)
		return
	}
	if _, err := runtimeidentity.AgentID(ids[0]); err != nil {
		skillInstallError(w, skillinstall.ErrInvalid)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
	defer cancel()
	view, _, err := s.collectSkillInstallationTargets(ctx, ids[0])
	if err != nil {
		skillInstallError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, view)
}

// This resolver never accepts an absolute path from the request and never uses
// SkillDirs or transient scan cwd as project membership. Discovery identifies
// an eligible location only; the install plan/apply still authorize the write.
func (s *Server) resolveSkillInstallTarget(ctx context.Context, instanceID, targetID string) (skillinstall.ScopedTarget, error) {
	instance, selections, err := s.skillInstallationSelections(ctx, instanceID)
	if err != nil {
		return skillinstall.ScopedTarget{}, err
	}
	var selected *skillInstallSelection
	for _, candidate := range selections {
		id, err := skillinstall.ScopedTargetID(instanceID, candidate.scope, candidate.root)
		if err != nil {
			return skillinstall.ScopedTarget{}, err
		}
		if id == targetID {
			if selected != nil {
				return skillinstall.ScopedTarget{}, skillinstall.ErrChanged
			}
			copy := candidate
			selected = &copy
		}
	}
	if selected == nil {
		return skillinstall.ScopedTarget{}, skillinstall.ErrChanged
	}
	// Runtime checks revalidate only the selected live scope, not every other
	// registered project's filesystem on each operation.
	return skillinstall.InspectScopedTarget(ctx, instance, selected.scope, selected.root, s.skillTargetDisplay(selected.root, selected.scope))
}

type skillInstallSelection struct{ scope, root string }

func (s *Server) skillInstallationSelections(ctx context.Context, id string) (skillinstall.Target, []skillInstallSelection, error) {
	if runtime.GOOS != "windows" {
		return skillinstall.Target{}, nil, skillinstall.ErrChanged
	}
	instance, err := s.resolveRuntimeIdentityTarget(ctx, id)
	if err != nil || instance.Platform != "workbuddy" {
		return skillinstall.Target{}, nil, skillinstall.ErrChanged
	}
	instance.Display = s.skillTargetDisplay(instance.Root, "user")
	roots, _, err := s.d.Store.LoadDiscoveryRoots()
	if err != nil {
		return skillinstall.Target{}, nil, skillinstall.ErrUnavailable
	}
	selections := []skillInstallSelection{{"user", instance.Root}}
	for _, root := range roots.ProjectDirs {
		selections = append(selections, skillInstallSelection{"project", root})
	}
	return instance, selections, nil
}

func (s *Server) collectSkillInstallationTargets(ctx context.Context, id string) (skillInstallTargetsView, map[string]skillinstall.ScopedTarget, error) {
	view := skillInstallTargetsView{SchemaVersion: "local-skill-install-targets/v1", InstanceID: id, Targets: []skillInstallTargetView{}}
	accepted := map[string]skillinstall.ScopedTarget{}
	instance, selections, err := s.skillInstallationSelections(ctx, id)
	if err != nil {
		return view, nil, err
	}
	seen := map[string]int{}
	configIdentity := ""
	for _, selected := range selections {
		if err := ctx.Err(); err != nil {
			return view, nil, err
		}
		targetID, err := skillinstall.ScopedTargetID(id, selected.scope, selected.root)
		if err != nil {
			return view, nil, skillinstall.ErrChanged
		}
		if previous, duplicate := seen[targetID]; duplicate {
			code := "target_ambiguous"
			view.Targets[previous].Available, view.Targets[previous].ErrorCode = false, &code
			delete(accepted, targetID)
			continue
		}
		shown := s.skillTargetDisplay(selected.root, selected.scope)
		suffix := "/skills"
		if selected.scope == "project" {
			suffix = "/.codebuddy/skills"
		}
		item := skillInstallTargetView{TargetID: targetID, InstanceID: id, Platform: "workbuddy", Scope: selected.scope,
			RootDisplay: shown, TargetDisplay: shown + suffix, FilesystemProfile: string(runtimeaction.FilesystemWindowsLocalDriveV1)}
		target, err := skillinstall.InspectScopedTarget(ctx, instance, selected.scope, selected.root, shown)
		if err := ctx.Err(); err != nil {
			return view, nil, err
		}
		if err == nil && target.Reference.TargetID == targetID {
			if configIdentity != "" && configIdentity != target.Reference.ConfigRootIdentityDigest {
				return view, nil, skillinstall.ErrChanged
			}
			configIdentity = target.Reference.ConfigRootIdentityDigest
			item.Available = true
			accepted[targetID] = target
		} else {
			code := "target_unavailable"
			item.ErrorCode = &code
		}
		seen[targetID] = len(view.Targets)
		view.Targets = append(view.Targets, item)
	}
	return view, accepted, nil
}

// Displays cannot be used to recover an absolute config/project path. Keep a
// home-relative name when possible; externally registered roots use a label.
func (s *Server) skillTargetDisplay(path, scope string) string {
	home := s.d.Home
	if home == "" {
		home, _ = os.UserHomeDir()
	}
	if home != "" {
		rel, err := filepath.Rel(home, path)
		if err == nil && rel == "." {
			return "~"
		}
		if err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) && !filepath.IsAbs(rel) {
			return "~/" + filepath.ToSlash(rel)
		}
	}
	if scope == "user" {
		return "<workbuddy-config>"
	}
	return "<registered-project>/" + filepath.Base(path)
}

func (s *Server) inventoryWorkBuddyRoot() (string, bool) {
	root, _, err := s.workBuddyRoot()
	return root, err != nil
}
