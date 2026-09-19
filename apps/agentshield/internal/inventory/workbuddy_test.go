package inventory

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func workBuddyInventoryFixture(t *testing.T) Options {
	t.Helper()
	home := t.TempDir()
	root := filepath.Join(home, "selected-workbuddy")
	project := filepath.Join(home, "registered-project")
	write(t, filepath.Join(root, "settings.json"), `{}`)
	write(t, filepath.Join(root, "skills", "same", "SKILL.md"), "---\nname: same\n---\nUser version\n")
	write(t, filepath.Join(home, ".workbuddy", "skills", "wrong-root", "SKILL.md"), "---\nname: wrong-root\n---\n")
	write(t, filepath.Join(home, ".codebuddy", "settings.json"), `{}`)
	write(t, filepath.Join(project, ".codebuddy", "skills", "same", "SKILL.md"), "---\nname: same\n---\nProject version\n")
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	return Options{Home: home, WorkBuddyConfigDir: root, ProjectDirs: []string{project}, Key: key, Version: "fixture"}
}

func TestWorkBuddyInventoryUsesExplicitRootAndSharedProjectEvidence(t *testing.T) {
	opts := workBuddyInventoryFixture(t)
	report, err := Run(opts)
	if err != nil {
		t.Fatal(err)
	}
	owner := "agent:workbuddy:" + hermeshome.Identifier(opts.WorkBuddyConfigDir)
	var user, project Candidate
	var profile Candidate
	for _, candidate := range report.Candidates {
		if candidate.SourceType == "workbuddy_profile" && candidate.CandidateID == owner {
			profile = candidate
		}
		if candidate.Name == "wrong-root" {
			t.Fatal("custom root fell back to Home/.workbuddy")
		}
		if candidate.SourceType != "skill_dir" {
			continue
		}
		switch candidate.Attributes["workbuddy_scope"] {
		case "user":
			user = candidate
		case "project":
			project = candidate
		}
	}
	// Candidate and Evidence have distinct source-type vocabularies. The
	// instance metadata must be a contract-valid manifest, bound to this root.
	if profile.CandidateID == "" || len(profile.EvidenceIDs) != 1 {
		t.Fatal("WorkBuddy instance lacks its own directory metadata evidence")
	}
	metadata, err := canon.Marshal(map[string]any{
		"instance_id": hermeshome.Identifier(opts.WorkBuddyConfigDir), "configuration_directory_exists": true,
	})
	if err != nil {
		t.Fatal(err)
	}
	expectedHash := sha256.Sum256(metadata)
	directoryEvidence := 0
	for _, evidence := range report.Evidence {
		if evidence.EvidenceID != profile.EvidenceIDs[0] {
			continue
		}
		directoryEvidence++
		if evidence.SourceType != "manifest" || evidence.SourceLocator != profile.SourceLocator ||
			evidence.ContentHash != hex.EncodeToString(expectedHash[:]) {
			t.Fatal("WorkBuddy directory metadata used an invalid evidence type or lost its instance binding")
		}
	}
	if directoryEvidence != 1 {
		t.Fatal("WorkBuddy directory metadata reference is missing or ambiguous")
	}
	if user.CandidateID == "" || project.CandidateID == "" || user.CandidateID == project.CandidateID || user.ArtifactDigest == project.ArtifactDigest {
		t.Fatal("project priority collapsed separate installed contents")
	}
	if project.Framework != "unknown" || project.Attributes["consumer_platforms"] != "codebuddy,workbuddy" || project.Attributes["workbuddy_selection"] != "unverified" {
		t.Fatal("shared location was assigned to one native host or claimed selected", project)
	}
	consumers := map[string]bool{}
	for _, relationship := range report.Relationships {
		if relationship.SkillID == project.CandidateID {
			if relationship.State != "inferred" {
				t.Fatal("directory association became authority")
			}
			consumers[relationship.SourceID] = true
		}
	}
	if !consumers[owner] || !consumers["platform:codebuddy"] || len(consumers) != 2 {
		t.Fatal("shared physical Skill lost a distinct consumer", consumers)
	}
	evidenceCount := 0
	for _, evidence := range report.Evidence {
		if evidence.SourceType == "skill_dir" && evidence.SourceLocator == project.SourceLocator {
			evidenceCount++
		}
	}
	if evidenceCount != 1 {
		t.Fatal("shared directory was counted as multiple physical observations", evidenceCount)
	}
	preview := Preview(opts)
	platforms := map[string]bool{}
	for _, item := range preview {
		if strings.Contains(item.Path, "/.workbuddy/") {
			t.Fatal("preview disagrees with selected configuration root")
		}
		if strings.HasSuffix(item.Path, "registered-project/.codebuddy/skills") {
			platforms[item.Platform] = true
		}
	}
	if !platforms["workbuddy"] || !platforms["codebuddy"] {
		t.Fatal("preview merged distinct host associations", platforms)
	}
}

func TestWorkBuddyInventoryDoesNotPromoteTransientOrDisabledRoots(t *testing.T) {
	for _, mode := range []string{"cwd", "skill-dir", "disabled", "missing-config"} {
		t.Run(mode, func(t *testing.T) {
			opts := workBuddyInventoryFixture(t)
			project := opts.ProjectDirs[0]
			switch mode {
			case "cwd":
				opts.ProjectDirs = nil
				opts.Cwd = project
			case "skill-dir":
				opts.ProjectDirs = nil
				opts.SkillDirs = []string{filepath.Join(project, ".codebuddy", "skills")}
			case "disabled":
				opts.WorkBuddyDisabled = true
			case "missing-config":
				opts.WorkBuddyConfigDir += "-missing"
			}
			report, err := Run(opts)
			if err != nil {
				t.Fatal(err)
			}
			for _, candidate := range report.Candidates {
				if candidate.Attributes["workbuddy_scope"] == "project" {
					t.Fatal("unregistered or unavailable host acquired project association")
				}
				if mode == "disabled" || mode == "missing-config" {
					if candidate.Framework == "workbuddy" || candidate.Attributes["workbuddy_scope"] != "" {
						t.Fatal("unavailable configured root fell back")
					}
				}
			}
			if mode == "disabled" || mode == "missing-config" {
				for _, item := range Preview(opts) {
					if item.Platform == "workbuddy" {
						t.Fatal("preview fell back to an unavailable configuration root")
					}
				}
			}
		})
	}
}
