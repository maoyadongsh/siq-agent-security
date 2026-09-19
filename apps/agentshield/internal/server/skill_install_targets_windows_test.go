package server

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

func workBuddyTargetsFixture(t *testing.T) (*Server, string, string, string) {
	t.Helper()
	s, st := newServer(t, "block")
	root := filepath.Join(s.d.Home, "selected-workbuddy")
	project := filepath.Join(s.d.Home, "registered-project")
	skillOnly := filepath.Join(s.d.Home, "scan-only")
	for _, path := range []string{root, project, skillOnly, filepath.Join(s.d.Home, ".workbuddy")} {
		if err := os.MkdirAll(path, 0700); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("WORKBUDDY_CONFIG_DIR", root)
	t.Setenv("CODEBUDDY_CONFIG_DIR", skillOnly)
	roots, revision, err := st.LoadDiscoveryRoots()
	if err != nil {
		t.Fatal(err)
	}
	roots.ProjectDirs, roots.SkillDirs = []string{project}, []string{skillOnly}
	if err := st.SaveDiscoveryRoots(roots, revision); err != nil {
		t.Fatal(err)
	}
	return s, hermeshome.Identifier(root), root, project
}

func TestWorkBuddySkillTargetsAreReadOnlyAndInstanceBound(t *testing.T) {
	s, instance, root, project := workBuddyTargetsFixture(t)
	route := "/v1/skill-installation-targets?instance_id=" + instance
	code, body := call(t, s, "GET", route, token, nil)
	if code != 200 {
		t.Fatal(code, body)
	}
	raw, err := json.Marshal(body)
	var view skillInstallTargetsView
	if err != nil || json.Unmarshal(raw, &view) != nil || view.SchemaVersion != "local-skill-install-targets/v1" || view.InstanceID != instance || view.PlatformChanges || len(view.Targets) != 2 {
		t.Fatal("invalid or excessive target discovery", body)
	}
	if strings.Contains(string(raw), root) || strings.Contains(string(raw), filepath.ToSlash(root)) || strings.Contains(string(raw), "identity_digest") {
		t.Fatal("target listing leaked physical identity or absolute root")
	}
	for _, item := range view.Targets {
		if !item.Available || item.ErrorCode != nil || item.InstanceID != instance || item.Platform != "workbuddy" {
			t.Fatal("verified target unavailable or misattributed", item)
		}
		target, err := s.resolveSkillInstallTarget(context.Background(), instance, item.TargetID)
		if err != nil || target.Instance.Root != root || target.Reference.ExistingParentRelativePath != "" {
			t.Fatal("resolver lost host/scope separation", err)
		}
		if item.Scope == "project" && target.ScopeRoot != project || item.Scope == "user" && target.ScopeRoot != root {
			t.Fatal("target scope changed its selected root")
		}
		if _, err := s.resolveSkillInstallTarget(context.Background(), "hi-"+strings.Repeat("0", 32), item.TargetID); err == nil {
			t.Fatal("another instance borrowed a discovered target")
		}
	}
	for _, path := range []string{filepath.Join(root, "skills"), filepath.Join(project, ".codebuddy"), filepath.Join(root, ".siq-agent-security-installs"), filepath.Join(project, ".siq-agent-security-installs")} {
		if _, err := os.Lstat(path); !os.IsNotExist(err) {
			t.Fatal("target discovery created installation directories", err)
		}
	}
	if _, err := s.resolveSkillTarget(context.Background(), instance); err == nil {
		t.Fatal("v1 silently enabled WorkBuddy")
	}
	if code, _ := call(t, s, "GET", route, "", nil); code != 401 {
		t.Fatal("anonymous target discovery", code)
	}
	for _, query := range []string{"", "?instance_id=bad", "?instance_id=" + instance + "&instance_id=" + instance, "?instance_id=" + instance + "&root=C:/other", "?instance_id=" + instance + "&%xx=ignored"} {
		if code, out := call(t, s, "GET", "/v1/skill-installation-targets"+query, token, nil); code != 400 {
			t.Fatal("untrusted selection accepted", code, out)
		}
	}
	if code, _ := call(t, s, "POST", route, token, nil); code != 405 {
		t.Fatal("discovery accepted a write method", code)
	}
}

func TestWorkBuddySkillTargetsRecheckParentsAndNeverFallback(t *testing.T) {
	s, instance, root, project := workBuddyTargetsFixture(t)
	id, err := skillinstall.ScopedTargetID(instance, "project", project)
	if err != nil {
		t.Fatal(err)
	}
	before, err := s.resolveSkillInstallTarget(context.Background(), instance, id)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(project, project+"-old"); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(project, 0700); err != nil {
		t.Fatal(err)
	}
	after, err := s.resolveSkillInstallTarget(context.Background(), instance, id)
	if err != nil || before.Reference.TargetID != after.Reference.TargetID || before.Reference.RootIdentityDigest == after.Reference.RootIdentityDigest {
		t.Fatal("replacement silently retained old physical identity", err)
	}
	parent := filepath.Join(project, ".codebuddy")
	if err := os.WriteFile(parent, []byte("foreign ordinary file"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.resolveSkillInstallTarget(context.Background(), instance, id); err == nil {
		t.Fatal("foreign target parent accepted")
	}
	view, _, err := s.collectSkillInstallationTargets(context.Background(), instance)
	if err != nil {
		t.Fatal(err)
	}
	if len(view.Targets) != 2 || !view.Targets[0].Available || view.Targets[1].Available || view.Targets[1].TargetID != id || view.Targets[1].ErrorCode == nil {
		t.Fatal("unavailable project was hidden or converted to a user target", view)
	}
	if err := os.Remove(parent); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(parent, 0700); err != nil {
		t.Fatal(err)
	}
	next, err := s.resolveSkillInstallTarget(context.Background(), instance, id)
	if err != nil || next.Reference.ExistingParentRelativePath != ".codebuddy" {
		t.Fatal("existing parent evidence missing", err)
	}
	if _, err := os.Lstat(filepath.Join(parent, "skills")); !os.IsNotExist(err) {
		t.Fatal("inspection created the missing scan root", err)
	}
	t.Setenv("WORKBUDDY_CONFIG_DIR", root+"-missing")
	if _, _, err := s.collectSkillInstallationTargets(context.Background(), instance); err == nil {
		t.Fatal("missing selected root fell back to Home/.workbuddy")
	}
	openclaw := filepath.Join(s.d.Home, ".openclaw")
	if err := os.Mkdir(openclaw, 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("WORKBUDDY_CONFIG_DIR", openclaw)
	if _, _, err := s.collectSkillInstallationTargets(context.Background(), hermeshome.Identifier(openclaw)); err == nil {
		t.Fatal("cross-platform root ambiguity accepted")
	}
}
