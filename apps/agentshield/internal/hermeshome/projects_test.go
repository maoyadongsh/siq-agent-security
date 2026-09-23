package hermeshome

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestRegisteredProjectsPreserveIdentityAndScope(t *testing.T) {
	home, project := t.TempDir(), t.TempDir()
	defaultRoot := filepath.Join(home, ".hermes", "profiles", "work")
	one := filepath.Join(project, ".hermes", "profiles", "work")
	two := filepath.Join(project, "agents", "hermes", "profiles", "work")
	hidden := filepath.Join(project, "arbitrary", "profiles", "work")
	for _, p := range []string{defaultRoot, one, two, hidden} {
		marker(t, p)
	}
	o := Options{Home: home, ProjectDirs: []string{project, project}, OS: "linux"}
	result := Scan(o)
	if len(result.Issues) != 0 {
		t.Fatal(result.Issues)
	}
	found := map[string]Root{}
	for _, r := range result.Roots {
		found[r.Path] = r
	}
	if len(found) != 4 {
		t.Fatalf("wrong roots: %+v", result)
	}
	for _, p := range []string{one, two} {
		r, ok := found[p]
		if !ok || r.Source != "registered_project" || r.Active || r.Default || r.ID != Identifier(p) {
			t.Fatal("project identity or authority incorrect")
		}
		legacy, err := Resolve(Options{Home: home, Override: p, OS: "linux"}, r.ID)
		if err != nil || legacy.CandidateID != r.CandidateID {
			t.Fatal("environment and project identity differ")
		}
		if _, err := Resolve(Options{Home: home, OS: "linux"}, r.ID); err == nil {
			t.Fatal("unregistered project exposed")
		}
	}
	if found[defaultRoot].CandidateID != "agent:hermes:work" {
		t.Fatal("legacy identity changed")
	}
	if err := os.Remove(filepath.Join(one, "config.yaml")); err != nil {
		t.Fatal(err)
	}
	if _, err := Resolve(o, Identifier(one)); err == nil {
		t.Fatal("marker removal still resolves")
	}
	unavailable := Scan(Options{Home: home, ProjectDirs: []string{project}, ProjectScopeUnavailable: true, OS: "linux"})
	if len(unavailable.Roots) != 2 || !contains(unavailable.Issues, "project_scope_unreadable") {
		t.Fatal("unreadable scope exposed project")
	}
}

func TestRegisteredProjectAliasesAndEnumerationLimits(t *testing.T) {
	home, project, outside := t.TempDir(), t.TempDir(), t.TempDir()
	marker(t, filepath.Join(outside, "profiles", "external"))
	if err := os.Symlink(outside, filepath.Join(project, ".hermes")); err != nil {
		t.Skip(err)
	}
	result := Scan(Options{Home: home, ProjectDirs: []string{project}, OS: "linux"})
	if len(result.Roots) != 1 || !contains(result.Issues, "unsafe_project_profile") {
		t.Fatal("project alias followed")
	}
	for _, p := range []string{"relative", project + string(filepath.Separator) + "..", `\\server\share`} {
		result = Scan(Options{Home: home, ProjectDirs: []string{p}, OS: "linux"})
		if len(result.Issues) == 0 || len(result.Roots) != 1 {
			t.Fatal("invalid project accepted")
		}
	}
	tooMany := make([]string, 17)
	for i := range tooMany {
		tooMany[i] = project
	}
	if result = Scan(Options{Home: home, ProjectDirs: tooMany, OS: "linux"}); !contains(result.Issues, "project_limit") {
		t.Fatal("project limit missing")
	}
	if err := os.Remove(filepath.Join(project, ".hermes")); err != nil {
		t.Fatal(err)
	}
	for _, layout := range []string{".hermes", filepath.Join("agents", "hermes")} {
		base := filepath.Join(project, layout)
		marker(t, base)
		for i := 0; i < MaxProfiles; i++ {
			marker(t, filepath.Join(base, "profiles", fmt.Sprintf("profile-%03d", i)))
		}
	}
	result = Scan(Options{Home: home, ProjectDirs: []string{project}, OS: "linux"})
	if len(result.Roots) != 129 || !contains(result.Issues, "project_profile_limit") {
		t.Fatal("aggregate project limit missing")
	}
}
