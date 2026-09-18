package state

import (
	"errors"
	"reflect"
	"testing"
)

func TestWindowsGrantNamespaceAliasesCannotPublish(t *testing.T) {
	for _, subdir := range []string{"grants", "GRANTS", "grants/.", "grants/sub/.."} {
		t.Run(subdir, func(t *testing.T) {
			s, err := Open(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			before := treeSnapshot(t, s.Dir)
			document := map[string]any{"schema_version": "grant/v2", "filesystem_profile": "windows-local-drive/v1"}
			if err := s.PutVersioned(subdir, "unactivated", document); !errors.Is(err, ErrGrantProfileActivation) {
				t.Fatal("namespace alias bypassed activation barrier")
			}
			if _, err := s.PutVersionedCAS(subdir, "unactivated", -1, document); !errors.Is(err, ErrGrantProfileActivation) {
				t.Fatal("CAS namespace alias bypassed activation barrier")
			}
			if !reflect.DeepEqual(before, treeSnapshot(t, s.Dir)) {
				t.Fatal("rejected namespace alias changed state")
			}
		})
	}
}
