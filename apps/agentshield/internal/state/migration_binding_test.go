package state

import (
	"errors"
	"reflect"
	"testing"
)

func TestBoundMigrationChecksBeforeWritesAndUnderLifecycleLock(t *testing.T) {
	s := migrationFixture(t)
	id, err := s.DirectoryID()
	if err != nil {
		t.Fatal(err)
	}
	before, err := snapshotMigrationTree(s.Dir, false)
	if err != nil {
		t.Fatal(err)
	}
	for _, wrong := range []string{"", "other-directory"} {
		if _, err := s.MigrateStateBound("fixture", wrong, func() error { return nil }); err == nil {
			t.Fatal("wrong binding accepted")
		}
	}
	if _, err := s.MigrateStateBound("fixture", id, func() error { return errors.New("executable changed") }); err == nil {
		t.Fatal("changed executable accepted")
	}
	after, err := snapshotMigrationTree(s.Dir, false)
	if err != nil || !reflect.DeepEqual(before, after) {
		t.Fatal("binding rejection wrote state")
	}
	w, err := AcquireScopedWriter(s.Dir, "service-control")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.MigrateStateBound("fixture", id, func() error { return nil }); err == nil {
		t.Fatal("running lifecycle accepted")
	}
	if err := w.Release(); err != nil {
		t.Fatal(err)
	}
	calls := 0
	if _, err := s.MigrateStateBound("fixture", id, func() error { calls++; return nil }); err != nil {
		t.Fatal(err)
	}
	if calls < 4 {
		t.Fatal("binding not rechecked at commit boundaries")
	}
}
