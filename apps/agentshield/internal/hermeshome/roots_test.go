package hermeshome

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func marker(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(path, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(path, "config.yaml"), []byte("model: fixture\n"), 0600); err != nil {
		t.Fatal(err)
	}
}
func TestSeparateHomesPreserveIdentityAcrossConfigChanges(t *testing.T) {
	home := t.TempDir()
	base := LegacyRoot(home)
	named := filepath.Join(base, "profiles", "work")
	custom := filepath.Join(t.TempDir(), "custom")
	other := filepath.Join(custom, "profiles", "work")
	for _, path := range []string{base, named, other} {
		marker(t, path)
	}
	scan := Scan(Options{Home: home, Override: other, OS: "linux"})
	if len(scan.Roots) != 4 {
		t.Fatalf("want 4 independent roots: %+v", scan)
	}
	seen := map[string]bool{}
	candidate := map[string]bool{}
	active := 0
	for _, root := range scan.Roots {
		if seen[root.ID] || candidate[root.CandidateID] {
			t.Fatal("identity collision")
		}
		seen[root.ID] = true
		candidate[root.CandidateID] = true
		if root.Active {
			active++
		}
		if root.Path == named && root.CandidateID != "agent:hermes:work" {
			t.Fatal("legacy identity changed")
		}
	}
	if active != 1 {
		t.Fatal("active root not resolved")
	}
	if err := os.WriteFile(filepath.Join(named, "config.yaml"), []byte("model: changed\n"), 0600); err != nil {
		t.Fatal(err)
	}
	for _, root := range Scan(Options{Home: home, Override: other, OS: "linux"}).Roots {
		if !seen[root.ID] {
			t.Fatal("config changed instance identity")
		}
	}
}
func TestRejectsUntrustedRootsAndLimitsEnumeration(t *testing.T) {
	home := t.TempDir()
	result := Scan(Options{Home: home, Override: "relative", OS: "linux"})
	if len(result.Issues) == 0 {
		t.Fatal("relative override silently accepted")
	}
	base := LegacyRoot(home)
	marker(t, base)
	outside := t.TempDir()
	marker(t, outside)
	link := filepath.Join(base, "profiles", "linked")
	if err := os.MkdirAll(filepath.Dir(link), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, link); err != nil {
		t.Skip(err)
	}
	result = Scan(Options{Home: home, OS: "linux"})
	if len(result.Roots) != 1 || len(result.Issues) == 0 {
		t.Fatal("symlink profile discovered")
	}
	if _, err := Resolve(Options{Home: home, OS: "linux"}, "../../outside"); err == nil {
		t.Fatal("unknown identity resolved")
	}
}
func TestWindowsAndPOSIXLocationsAreDistinct(t *testing.T) {
	home := t.TempDir()
	app := filepath.Join(home, "AppData", "Local")
	result := Scan(Options{Home: home, LocalAppData: app, OS: "windows"})
	if !result.Roots[0].Default || result.Roots[0].Path != filepath.Join(app, "hermes") {
		t.Fatal("native Windows root missing")
	}
	if len(result.Roots) != 2 {
		t.Fatal("legacy Windows root compatibility missing")
	}
}

func TestProfileEnumerationBudget(t *testing.T) {
	home := t.TempDir()
	base := LegacyRoot(home)
	for i := 0; i < MaxProfiles+1; i++ {
		marker(t, filepath.Join(base, "profiles", fmt.Sprintf("profile-%03d", i)))
	}
	result := Scan(Options{Home: home, OS: "linux"})
	if len(result.Roots) > MaxProfiles+1 || !contains(result.Issues, "profile_limit") {
		t.Fatal("profile enumeration unbounded or limit invisible")
	}
}
