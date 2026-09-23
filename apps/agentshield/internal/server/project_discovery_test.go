package server

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
)

func projectProfileFixture(t *testing.T, s *Server) (string, string) {
	t.Helper()
	s.d.HermesHome = ""
	s.d.HermesOS = "linux"
	s.d.HermesCLI = filepath.Join(s.d.Home, "absent-cli")
	project := filepath.Join(s.d.Home, "research-project")
	profile := filepath.Join(project, "agents", "hermes", "profiles", "siq_analysis")
	if err := os.MkdirAll(filepath.Join(profile, "skills", "report"), 0700); err != nil {
		t.Fatal(err)
	}
	for name, content := range map[string]string{
		"config.yaml":            "model:\n  default: project-fixture\n  provider: custom:fixture\n  base_url: http://127.0.0.1:1234/v1\n  key_env: SIQ_PROJECT_TEST_MISSING_KEY\n",
		"skills/report/SKILL.md": "---\nname: project-report\ndescription: Read a synthetic public report.\n---\n# Report\n",
	} {
		if err := os.WriteFile(filepath.Join(profile, name), []byte(content), 0600); err != nil {
			t.Fatal(err)
		}
	}
	return project, profile
}
func registerProject(t *testing.T, s *Server, project string) {
	t.Helper()
	scope, rev, err := s.d.Store.LoadDiscoveryRoots()
	if err != nil {
		t.Fatal(err)
	}
	scope.ProjectDirs = append(scope.ProjectDirs, project)
	if err := s.d.Store.SaveDiscoveryRoots(scope, rev); err != nil {
		t.Fatal(err)
	}
}
func TestRegisteredProjectDiscoveryAndManagementShareExactIdentity(t *testing.T) {
	s, _ := newServer(t, "block")
	project, profile := projectProfileFixture(t, s)
	id := hermeshome.Identifier(profile)
	if _, err := s.resolveRuntimeIdentityTarget(context.Background(), id); err == nil {
		t.Fatal("unregistered project resolved")
	}
	registerProject(t, s, project)
	const route = "/v1/adapter/instances?platform=hermes&include_projects=true"
	if res := sessionRequest(t, s, "GET", route, nil, token, nil, nil); res.Code != 403 {
		t.Fatal("decision credential listed project")
	}
	code, catalog := call(t, s, "GET", route, token, nil)
	if code != 200 || catalog["schema_version"] != "local-adapter-instances/v3" {
		t.Fatal(catalog)
	}
	found := false
	for _, v := range catalog["instances"].([]any) {
		r := v.(map[string]any)
		if r["instance_id"] == id {
			found = r["source"] == "registered_project" && r["active"] == false
		}
	}
	if !found {
		t.Fatal("project instance missing")
	}
	_, old := call(t, s, "GET", "/v1/adapter/instances?platform=hermes", token, nil)
	for _, v := range old["instances"].([]any) {
		if v.(map[string]any)["instance_id"] == id {
			t.Fatal("legacy contract expanded")
		}
	}
	target, err := s.resolveRuntimeIdentityTarget(context.Background(), id)
	if err != nil || target.Root != profile {
		t.Fatal("runtime target mismatch")
	}
	models, _ := s.modelTargets()
	if len(models) != 1 || models[0].Item.InstanceID != id || models[0].Item.Model != "project-fixture" {
		t.Fatal("model target mismatch")
	}
	if err := s.Refresh(""); err != nil {
		t.Fatal(err)
	}
	s.proj.mu.RLock()
	report := s.proj.snap.Report
	s.proj.mu.RUnlock()
	owner := ""
	for _, c := range report.Candidates {
		if c.Attributes["instance_id"] == id {
			owner = c.CandidateID
		}
	}
	if owner == "" {
		t.Fatal("inventory instance missing")
	}
	linked := false
	for _, r := range report.Relationships {
		if r.SourceID == owner && r.State == "inferred" {
			linked = true
		}
	}
	if !linked {
		t.Fatal("profile Skill association missing")
	}
	code, plan := call(t, s, "POST", "/v1/adapter/preview", token, map[string]any{"platform": "hermes", "action": "install", "instance_id": id})
	if code != 200 || plan["instance_id"] != id {
		t.Fatal("project preview failed")
	}
	if err := os.Remove(filepath.Join(profile, "config.yaml")); err != nil {
		t.Fatal(err)
	}
	if _, err := s.resolveRuntimeIdentityTarget(context.Background(), id); err == nil {
		t.Fatal("removed marker still resolves")
	}
	body := map[string]any{"platform": "hermes", "plan_id": plan["plan_id"], "plan_digest": plan["plan_digest"], "instance_id": id}
	if code, _ := call(t, s, "POST", "/v1/adapter/install", token, body); code != 409 {
		t.Fatal("stale project plan installed")
	}
	if _, err := os.Stat(filepath.Join(profile, "plugins")); !os.IsNotExist(err) {
		t.Fatal("stale plan wrote plugin")
	}
}
func TestProjectInstancesV3Contract(t *testing.T) {
	s, _ := newServer(t, "block")
	project, _ := projectProfileFixture(t, s)
	registerProject(t, s, project)
	for _, query := range []string{"include_projects=false", "include_projects=true&include_projects=true"} {
		if code, _ := call(t, s, "GET", "/v1/adapter/instances?platform=hermes&"+query, token, nil); code != 400 {
			t.Fatal("ambiguous query accepted")
		}
	}
	_, view := call(t, s, "GET", "/v1/adapter/instances?platform=hermes&include_projects=true", token, nil)
	for i, v := range view["instances"].([]any) {
		v.(map[string]any)["instance_id"] = fmt.Sprintf("hi-%032x", i+1)
	}
	raw, err := json.MarshalIndent(view, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), s.d.Home) {
		t.Fatal("fixture home leaked")
	}
	raw = append(raw, '\n')
	path := filepath.Join("..", "..", "testdata", "contracts", "adapter-instances.v3.json")
	if os.Getenv("SIQ_UPDATE_PROJECT_FIXTURES") == "1" {
		if err := os.WriteFile(path, raw, 0644); err != nil {
			t.Fatal(err)
		}
	}
	expected, err := os.ReadFile(path)
	if err != nil || string(expected) != string(raw) {
		t.Fatal("project contract fixture drift")
	}
}
