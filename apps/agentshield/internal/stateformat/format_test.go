package stateformat

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

func TestV2StrictContract(t *testing.T) {
	raw, e := os.ReadFile("../../testdata/contracts/local-state-format-v2.json")
	if e != nil {
		t.Fatal(e)
	}
	m, e := Decode(raw)
	if e != nil {
		t.Fatal(e)
	}
	var expected, actual any
	json.Unmarshal(raw, &expected)
	round, _ := json.Marshal(m)
	json.Unmarshal(round, &actual)
	if !reflect.DeepEqual(expected, actual) {
		t.Fatal("fixture drift")
	}
	for _, bad := range []string{
		strings.Replace(string(raw), `"min_writer": 2`, `"min_writer": 2,"min_writer":1`, 1),
		strings.Replace(string(raw), `"min_writer": 2`, `"MIN_WRITER": 2`, 1),
		strings.Replace(string(raw), `"min_writer": 2`, `"min_writer": null`, 1),
		strings.Replace(string(raw), `"min_writer": 2`, `"min_writer": 1`, 1),
		string(raw) + ` {}`, strings.Replace(string(raw), `"format_version": 2`, `"format_version": 1`, 1),
	} {
		if _, e := Decode([]byte(bad)); e == nil {
			t.Fatal("invalid marker accepted")
		}
	}
}

func TestCheckParentsAcceptsGoTempDir(t *testing.T) {
	dir := t.TempDir()
	if err := CheckParents(dir); err != nil {
		t.Fatalf("Go temp dir must be a usable state parent (darwin /var is a volume alias): %v", err)
	}
	missing := filepath.Join(dir, "new-instance")
	if err := CheckParents(missing); err != nil {
		t.Fatalf("missing child of a temp dir rejected: %v", err)
	}
}

func TestCheckParentsRejectsFileAndIntermediateSymlink(t *testing.T) {
	fileAncestor := filepath.Join(t.TempDir(), "not-a-dir")
	if err := os.WriteFile(fileAncestor, []byte("no"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := CheckParents(filepath.Join(fileAncestor, "state")); err == nil {
		t.Fatal("file ancestor accepted")
	}
	real := t.TempDir()
	alias := filepath.Join(t.TempDir(), "alias")
	if err := os.Symlink(real, alias); err != nil {
		t.Skip("symlink unavailable")
	}
	nested := filepath.Join(alias, "state")
	if err := os.Mkdir(nested, 0700); err != nil {
		t.Fatal(err)
	}
	if err := CheckParents(nested); err == nil {
		t.Fatal("intermediate directory symlink accepted")
	}
	if err := CheckParents(alias); err == nil {
		t.Fatal("state-root symlink accepted by CheckParents")
	}
	if err := LeafDirectory(real); err != nil {
		t.Fatalf("temp leaf directory rejected: %v", err)
	}
	if err := LeafDirectory(alias); err == nil {
		t.Fatal("leaf symlink accepted")
	}
}

func TestDarwinDirectoryAliasRequiresExactSystemTarget(t *testing.T) {
	for _, c := range []struct {
		name, link string
		allowed    bool
	}{
		{"/var", "private/var", true}, {"/tmp", "/private/tmp", true}, {"/etc", "private/etc", true},
		{"/var", "/private/tmp", false}, {"/tmp", "/untrusted/tmp", false},
		{"/custom", "/private/var", false}, {"/bin", "usr/bin", false},
		{"/home/var", "/private/var", false}, {"var", "private/var", false},
	} {
		if got := darwinDirectoryAlias(c.name, c.link); got != c.allowed {
			t.Errorf("alias %q -> %q: got %v", c.name, c.link, got)
		}
	}
}

func TestNonDarwinRootSymlinkStillRejected(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("existing Linux root alias probe")
	}
	info, err := os.Lstat("/bin")
	if err != nil || info.Mode()&os.ModeSymlink == 0 {
		t.Skip("no /bin symlink on this host")
	}
	if AcceptDirectory(info, "/bin") {
		t.Fatal("non-Darwin symlink accepted")
	}
	if err := CheckParents("/bin/siq-nonexistent-state-probe"); err == nil {
		t.Fatal("non-Darwin parent symlink accepted")
	}
}

func TestDarwinKnownAliasesAreAncestorsOnly(t *testing.T) {
	if runtime.GOOS != "darwin" {
		t.Skip("real Darwin filesystem required")
	}
	for _, name := range []string{"/var", "/tmp", "/etc"} {
		info, err := os.Lstat(name)
		if err != nil {
			t.Fatal(err)
		}
		if !AcceptDirectory(info, name) {
			t.Fatalf("system alias rejected: %s", name)
		}
		if info.Mode()&os.ModeSymlink != 0 && LeafDirectory(name) == nil {
			t.Fatalf("alias accepted as leaf: %s", name)
		}
	}
}
