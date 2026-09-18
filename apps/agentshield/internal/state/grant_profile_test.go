package state

import (
	"errors"
	"reflect"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestWindowsGrantCannotPublishBeforeCompatibilityActivation(t *testing.T) {
	s, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	g := grant.Grant{GrantID: "new-profile", SchemaVersion: "grant/v2", FilesystemProfile: "windows-local-drive/v1"}
	before := treeSnapshot(t, s.Dir)
	checks := []func() error{
		func() error { return s.PutGrant(g) },
		func() error { _, err := s.PutGrantCAS(g, -1); return err },
		func() error { _, err := s.CommitGrant(GrantCommit{Grant: g, ExpectedRevision: -1}); return err },
		func() error { return s.PutVersioned("grants", g.GrantID, map[string]any{"filesystem_profile": nil}) },
		func() error {
			return s.PutVersioned("grants", g.GrantID, map[string]any{"FILESYSTEM_PROFILE": "windows-local-drive/v1"})
		},
		func() error {
			_, err := s.PutVersionedCAS("grants", g.GrantID, -1, map[string]any{"schema_version": "grant/v2"})
			return err
		},
	}
	for _, check := range checks {
		if !errors.Is(check(), ErrGrantProfileActivation) {
			t.Fatal("new interpretation persisted before activation")
		}
		if !reflect.DeepEqual(before, treeSnapshot(t, s.Dir)) {
			t.Fatal("rejected activation changed state")
		}
	}
}
