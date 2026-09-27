package state

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestMigrationPreviewIsReadOnlyAndBoundToInstance(t *testing.T) {
	st := migrationFixture(t)
	before, err := snapshotMigrationTree(st.Dir, false)
	if err != nil {
		t.Fatal(err)
	}
	view, err := st.PreviewStateMigration()
	if err != nil {
		t.Fatal(err)
	}
	instance, err := st.ReadLocalInstance()
	if err != nil {
		t.Fatal(err)
	}
	directory, err := st.DirectoryID()
	if err != nil {
		t.Fatal(err)
	}
	if view.DirectoryID != directory || view.InstanceID != instance.InstanceID || view.Format != 1 || view.Entries == 0 || !view.ServiceStopRequired {
		t.Fatalf("preview identity: %+v", view)
	}
	if os.Getenv("SIQ_UPDATE_CONTRACT_FIXTURES") == "1" {
		raw, err := json.MarshalIndent(view, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join("..", "..", "testdata", "contracts", "local-state-migration-preview.json"), append(raw, '\n'), 0600); err != nil {
			t.Fatal(err)
		}
	}
	after, err := snapshotMigrationTree(st.Dir, false)
	if err != nil || !reflect.DeepEqual(before, after) {
		t.Fatal("preview mutated source")
	}
	missing := filepath.Join(t.TempDir(), "absent")
	if _, err := (&Store{Dir: missing}).PreviewStateMigration(); err == nil {
		t.Fatal("missing state accepted")
	}
	if _, err := os.Stat(missing); !os.IsNotExist(err) {
		t.Fatal("preview initialized state")
	}
}
