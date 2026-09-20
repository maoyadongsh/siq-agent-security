package inventory

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/runtimepath"
)

func (r *run) workBuddyRoot() (string, bool) {
	if r.opts.WorkBuddyDisabled {
		return "", false
	}
	root := r.opts.WorkBuddyConfigDir
	if root == "" {
		root = filepath.Join(r.opts.Home, ".workbuddy")
	}
	if !filepath.IsAbs(root) {
		return "", false
	}
	if runtime.GOOS == "windows" {
		live, err := runtimepath.InspectWindows(root, false)
		if err != nil || !live.IsDirectory() {
			return "", false
		}
	} else {
		if r.safePath(root) != nil {
			return "", false
		}
		if info, err := os.Lstat(root); err != nil || !info.IsDir() {
			return "", false
		}
	}
	return root, true
}

func (r *run) workBuddyDiscovery(seen map[string]bool) bool {
	root, ok := r.workBuddyRoot()
	if !ok {
		return false
	}
	p := platformSpec{name: "workbuddy", framework: "workbuddy"}
	r.platformConfig(p, filepath.Join(root, "settings.json"), "instances/"+hermeshome.Identifier(root)+"/settings.json")
	id := hermeshome.Identifier(root)
	owner := "agent:workbuddy:" + id
	locator := "workbuddy://instances/" + id
	// This evidence hashes only observed directory metadata. It is not a
	// content digest, an installed-host assertion, or execution attribution.
	raw, _ := canon.Marshal(map[string]any{"instance_id": id, "configuration_directory_exists": true})
	sum := sha256.Sum256(raw)
	evidence := r.evidence("manifest", locator, hex.EncodeToString(sum[:]))
	r.report.Candidates = append(r.report.Candidates, Candidate{CandidateID: owner, SourceType: "workbuddy_profile", SourceLocator: locator,
		DiscoveredAt: r.now, Name: "workbuddy", Framework: "workbuddy", Confidence: 1, Status: "candidate",
		Attributes: map[string]string{"platform": "workbuddy", "instance_id": id, "config_dir": redactHome(root, r.opts.Home), "detection": "configuration_directory"}, EvidenceIDs: []string{evidence}})
	userSkills := filepath.Join(root, "skills")
	r.addRootOwners(userSkills, []string{owner}, "workbuddy_user_directory")
	r.skillDir(p, userSkills, seen)
	// Only persisted ProjectDirs associate WorkBuddy with a project. A scan's
	// transient cwd and explicit SkillDirs do not acquire that host meaning.
	for _, project := range r.opts.ProjectDirs {
		skills := filepath.Join(project, ".codebuddy", "skills")
		r.addRootOwners(skills, []string{owner}, "workbuddy_project_directory")
		r.skillDir(p, skills, seen)
	}
	return true
}

func (r *run) annotateWorkBuddyConsumers() {
	scopes := map[string]string{}
	for _, relationship := range r.report.Relationships {
		switch relationship.Basis {
		case "workbuddy_user_directory":
			if scopes[relationship.SkillID] == "" {
				scopes[relationship.SkillID] = "user"
			}
		case "workbuddy_project_directory":
			scopes[relationship.SkillID] = "project"
		}
	}
	for i := range r.report.Candidates {
		candidate := &r.report.Candidates[i]
		if scope := scopes[candidate.CandidateID]; scope != "" {
			candidate.Attributes["workbuddy_scope"] = scope
			candidate.Attributes["workbuddy_selection"] = "unverified"
		}
	}
}
