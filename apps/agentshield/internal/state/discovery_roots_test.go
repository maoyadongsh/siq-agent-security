package state

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestDiscoveryRootsRejectStaleWriteAndPreserveHistory(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	roots, rev, err := st.LoadDiscoveryRoots()
	if err != nil || rev != -1 {
		t.Fatalf("initial scope: %d, %v", rev, err)
	}
	roots.SkillDirs = []string{t.TempDir()}
	if err := st.SaveDiscoveryRoots(roots, rev); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(st.Dir, "discovery-roots", "scope.0.json")
	original, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	roots.ProjectDirs = []string{t.TempDir()}
	if err := st.SaveDiscoveryRoots(roots, rev); err == nil {
		t.Fatal("stale scope update accepted")
	}
	if err := st.SaveDiscoveryRoots(roots, 0); err != nil {
		t.Fatal(err)
	}
	unchanged, _ := os.ReadFile(path)
	if !bytes.Equal(original, unchanged) {
		t.Fatal("scope update overwrote history")
	}
	reopened, err := Open(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	got, rev, err := reopened.LoadDiscoveryRoots()
	if err != nil || rev != 1 || len(got.ProjectDirs) != 1 || len(got.SkillDirs) != 1 {
		t.Fatal("scope did not survive reopen")
	}
	if err := os.WriteFile(filepath.Join(st.Dir, "discovery-roots", "scope.2.json"), []byte("null"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := reopened.LoadDiscoveryRoots(); err == nil {
		t.Fatal("corrupt latest scope fell back to older scope")
	}
}

func TestDiscoveryRootsCombinedLimitAndInvalidPaths(t *testing.T) {
	base := t.TempDir()
	roots := DiscoveryRoots{SchemaVersion: "local-discovery-roots/v1", ProjectDirs: []string{}, SkillDirs: []string{}}
	for i := 0; i < 16; i++ {
		if i < 8 {
			roots.ProjectDirs = append(roots.ProjectDirs, filepath.Join(base, fmt.Sprint(i)))
		} else {
			roots.SkillDirs = append(roots.SkillDirs, filepath.Join(base, fmt.Sprint(i)))
		}
	}
	if !roots.valid() {
		t.Fatal("exact combined limit rejected")
	}
	roots.SkillDirs = append(roots.SkillDirs, filepath.Join(base, "extra"))
	if roots.valid() {
		t.Fatal("combined limit exceeded")
	}
	for _, paths := range [][]string{nil, {"relative"}, {base, base}, {base + "\n"}, {"//host/share"}} {
		roots.ProjectDirs, roots.SkillDirs = []string{}, paths
		if roots.valid() {
			t.Fatal("invalid scope accepted")
		}
	}
}
