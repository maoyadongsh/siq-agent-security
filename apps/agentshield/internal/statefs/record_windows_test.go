package statefs

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/privatefs"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func privateRecordFixture(t *testing.T) (string, string) {
	t.Helper()
	root := filepath.Join(t.TempDir(), "state")
	path := filepath.Join(root, "records", "record.json")
	if err := privatefs.MkdirAll(filepath.Dir(path)); err != nil {
		t.Fatal(err)
	}
	f, err := privatefs.CreateNew(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.WriteString(`{"fixture":"original"}`); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	return root, path
}

func TestPrivateRecordAbsenceRequiresCurrentPrivateDirectories(t *testing.T) {
	root, path := privateRecordFixture(t)
	absent := filepath.Join(filepath.Dir(path), "absent.json")
	if _, err := ReadPrivateRecord(root, absent, 128); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("valid absence rejected", err)
	}
	for _, target := range []string{root, filepath.Dir(path)} {
		restore := acltest.BroadenRead(t, root, target)
		if _, err := ReadPrivateRecord(root, absent, 128); err == nil || errors.Is(err, os.ErrNotExist) {
			t.Error("unsafe directory became absent record", err)
		}
		restore()
	}
	if _, err := ReadPrivateRecord(root, filepath.Join(root, "missing-directory", "absent.json"), 128); err == nil || errors.Is(err, os.ErrNotExist) {
		t.Fatal("missing directory became absent record", err)
	}
	if _, err := ReadPrivateRecord(filepath.Join(root, "missing-root"), filepath.Join(root, "missing-root", "file"), 128); err == nil || errors.Is(err, os.ErrNotExist) {
		t.Fatal("missing root became absent record", err)
	}
}

func TestPrivateRecordBoundsAndCurrentObjects(t *testing.T) {
	root, path := privateRecordFixture(t)
	if raw, err := ReadPrivateRecord(root, path, 128); err != nil || string(raw) != `{"fixture":"original"}` {
		t.Fatal("valid record rejected", string(raw), err)
	}
	for _, target := range []string{root, filepath.Dir(path), path} {
		restore := acltest.BroadenRead(t, root, target)
		if raw, err := ReadPrivateRecord(root, path, 128); err == nil || len(raw) != 0 {
			t.Error("current ACL expansion accepted", err)
		}
		restore()
	}
	if _, err := ReadPrivateRecord(root, path, 3); err == nil {
		t.Fatal("record bound ignored")
	}
	if _, err := ReadPrivateRecord(root, filepath.Join(root, "..", "foreign.json"), 128); err == nil {
		t.Fatal("foreign record accepted")
	}
	writer, err := os.OpenFile(path, os.O_RDWR, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := ReadPrivateRecord(root, path, 128); err == nil {
		t.Fatal("existing writer accepted")
	}
	writer.Close()
	if err := os.Link(path, path+"-alias"); err != nil {
		t.Fatal(err)
	}
	if _, err := ReadPrivateRecord(root, path, 128); err == nil {
		t.Fatal("hard-linked record accepted")
	}
	if err := os.Remove(path + "-alias"); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`{"fixture":"current"}`), 0600); err != nil {
		t.Fatal(err)
	}
	if raw, err := ReadPrivateRecord(root, path, 128); err != nil || string(raw) != `{"fixture":"current"}` {
		t.Fatal("next read reused stale record", string(raw), err)
	}
}

func TestPrivateRecordKeepsOuterAndNestedCompatibilityBarriers(t *testing.T) {
	for _, location := range []string{"outer", "nested", "migration"} {
		t.Run(location, func(t *testing.T) {
			root, path := privateRecordFixture(t)
			dir := root
			if location == "outer" {
				dir = filepath.Dir(root)
			} else if location == "nested" {
				dir = filepath.Dir(path)
			}
			marker := []byte(`{"schema":"state-format/v1","program_version":"future","format_version":999,"published_at":"2026-09-18T00:00:00Z"}`)
			name := filepath.Join(dir, stateformat.MarkerName)
			if location == "migration" {
				if err := privatefs.MkdirAll(filepath.Join(root, "logs")); err != nil {
					t.Fatal(err)
				}
				id, err := stateformat.DirectoryID(root)
				if err != nil {
					t.Fatal(err)
				}
				source := stateformat.Marker{Schema: "state-format/v2", ProgramVersion: "fixture", FormatVersion: 2, PublishedAt: "2026-09-18T00:00:00Z", MinReader: 2, MinWriter: 2, DirectoryID: id, InstanceID: strings.Repeat("a", 64)}
				target := source
				target.MinReader, target.MinWriter = 3, 3
				a, _ := json.Marshal(source)
				b, _ := json.Marshal(target)
				marker = stateformat.EncodeWindowsProfilePlan(stateformat.WindowsProfilePlan{Schema: stateformat.WindowsProfilePlanSchema, Profile: stateformat.WindowsResourceProfile, SourceMarker: string(a), TargetMarker: string(b), MigrationHash: "absent"})
				name = filepath.Join(root, stateformat.PlanName)
			}
			if err := os.WriteFile(name, marker, 0600); err != nil {
				t.Fatal(err)
			}
			if raw, err := ReadPrivateRecord(root, path, 128); err == nil || len(raw) != 0 || !errors.Is(err, stateformat.ErrIncompatible) {
				t.Fatal("compatibility barrier ignored", err)
			}
		})
	}
}
