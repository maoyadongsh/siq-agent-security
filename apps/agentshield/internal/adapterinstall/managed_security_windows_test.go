package adapterinstall

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/product"
)

func TestManagedConfigReplacementAndRollbackPreserveDeny(t *testing.T) {
	for _, name := range []string{product.Name + ".json", "settings.json", "inherited.json"} {
		t.Run(name, func(t *testing.T) {
			root := t.TempDir()
			path := filepath.Join(root, name)
			if err := os.WriteFile(path, []byte(`{"before":true}`), 0600); err != nil {
				t.Fatal(err)
			}
			if name != "inherited.json" {
				acltest.DenyExecute(t, root, path)
			}
			before, err := readImage(root, path, true)
			if err != nil {
				t.Fatal(err)
			}
			if name != "inherited.json" && !strings.Contains(before.Security, "(D;") {
				t.Fatal("deny missing from private recovery material")
			}
			after := before
			after.Data = []byte(`{"after":true}`)
			if err := writeImage(root, path, before, after); err != nil {
				t.Fatal(err)
			}
			live, err := readImage(root, path, true)
			if err != nil || !privatefs.EquivalentSecurity(live.Security, before.Security) {
				t.Fatalf("replacement changed descriptor: %v", err)
			}
			if err := writeImage(root, path, after, before); err != nil {
				t.Fatal(err)
			}
			live, err = readImage(root, path, true)
			if err != nil || !sameImage(live, before) {
				t.Fatalf("rollback changed bytes or descriptor: %v", err)
			}
			if err := privatefs.CheckDir(root); err != nil {
				t.Fatal(err)
			}

		})
	}
}

func TestManagedFileNewPublicationAndDeletedFileRestore(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "private", "settings.json")
	before := fileImage{}
	after := fileImage{Exists: true, Mode: 0600, Data: []byte("fixture")}
	if err := writeImage(root, path, before, after, true); err != nil {
		t.Fatal(err)
	}
	live, err := readImage(root, path, true)
	if err != nil {
		t.Fatal(err)
	}
	if live.Security == "" {
		t.Fatal("new file did not preserve private security")
	}
	if err := publishManagedSecurity(path, after, false, true); err == nil {
		t.Fatal("publication overwrote existing target")
	}
	if err := writeImage(root, path, live, before, true); err != nil {
		t.Fatal(err)
	}
	if err := writeImage(root, path, before, live, true); err != nil {
		t.Fatal(err)
	}
	recovered, err := readImage(root, path, true)
	if err != nil || !sameImage(live, recovered) {
		t.Fatal("restored file is not a private single-link byte/permission match", err)
	}
}
