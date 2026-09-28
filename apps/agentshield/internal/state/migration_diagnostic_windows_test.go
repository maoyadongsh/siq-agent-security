package state

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func TestWindowsMigrationDistinguishesHardlinksAndPermissions(t *testing.T) {
	for _, kind := range []string{"hardlink", "permissions"} {
		t.Run(kind, func(t *testing.T) {
			s := migrationFixture(t)
			rel := filepath.Join("grants", "revoked", "1.json")
			path := filepath.Join(s.Dir, rel)
			before, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			marker, _ := os.ReadFile(filepath.Join(s.Dir, stateformat.MarkerName))
			code := "state_migration_private_permissions"
			alias := filepath.Join(t.TempDir(), "outside-state-alias")
			if kind == "hardlink" {
				if err := os.Link(path, alias); err != nil {
					t.Fatal(err)
				}
				code = "state_migration_multiple_links"
			} else {
				acltest.BroadenRead(t, s.Dir, path)
			}
			_, err = s.MigrateState("diagnostic-fixture")
			var failure *MigrationObjectError
			if !errors.As(err, &failure) || failure.Code != code || failure.Object != filepath.ToSlash(rel) || !errors.Is(err, privatefs.ErrPrivate) {
				t.Fatalf("wrong migration reason: %v", err)
			}
			if strings.Contains(err.Error(), s.Dir) || strings.Contains(err.Error(), string(before)) {
				t.Fatal("private detail leaked")
			}
			after, _ := os.ReadFile(path)
			afterMarker, _ := os.ReadFile(filepath.Join(s.Dir, stateformat.MarkerName))
			if string(after) != string(before) || string(afterMarker) != string(marker) {
				t.Fatal("rejected migration changed business state")
			}
			if _, err := os.Lstat(filepath.Join(s.Dir, stateformat.PlanName)); !os.IsNotExist(err) {
				t.Fatal("preflight failure published migration")
			}
			if kind == "hardlink" {
				raw, err := os.ReadFile(alias)
				if err != nil || string(raw) != string(before) {
					t.Fatal("outside alias removed or changed")
				}
			}
		})
	}
}
