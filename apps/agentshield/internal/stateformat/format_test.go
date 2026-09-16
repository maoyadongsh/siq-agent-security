package stateformat

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
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
