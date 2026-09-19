package skillinstall

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/privatefs"
)

func TestWindowsSkillPlanReadRejectsBroadACL(t *testing.T) {
	f := setup(t)
	s := f.store
	p, _, err := s.Stage(nil, f.request)
	if err != nil {
		t.Fatal(err)
	}
	path := s.record(p.PlanID)
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"file", "plans", "store", "state"} {
		t.Run(name, func(t *testing.T) {
			target := path
			switch name {
			case "plans":
				target = filepath.Dir(path)
			case "store":
				target = s.dir
			case "state":
				target = s.authority.Dir
			}
			restore := acltest.BroadenRead(t, s.authority.Dir, target)
			if _, err := s.readPlan(p.PlanID); err == nil {
				t.Error("broad installation plan accepted")
			}
			after, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(before, after) {
				t.Fatal("plan changed")
			}
			if info, _ := os.Stat(target); info.IsDir() {
				if privatefs.CheckDir(target) == nil {
					t.Fatal("directory ACL repaired")
				}
			} else if privatefs.CheckFilePath(target) == nil {
				t.Fatal("file ACL repaired")
			}
			restore()
			if _, err := s.readPlan(p.PlanID); err != nil {
				t.Fatal("restored fixture unreadable", err)
			}
		})
	}
}

func TestWindowsSkillUpdatePlanReadRejectsBroadACL(t *testing.T) {
	f, op, req := readyUpdate(t)
	s := f.store
	p, _, err := s.StageUpdate(nil, op.InstallID, req)
	if err != nil {
		t.Fatal(err)
	}
	path := s.updateRecord(p.UpdateID)
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"file", "directory"} {
		t.Run(name, func(t *testing.T) {
			target := path
			if name == "directory" {
				target = filepath.Dir(path)
			}
			restore := acltest.BroadenRead(t, s.authority.Dir, target)
			if _, err := s.readUpdatePlan(context.Background(), p.UpdateID); err == nil {
				t.Error("broad update plan accepted")
			}
			after, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(before, after) {
				t.Fatal("update plan changed")
			}
			restore()
			if _, err := s.readUpdatePlan(context.Background(), p.UpdateID); err != nil {
				t.Fatal("restored fixture unreadable", err)
			}
		})
	}
}

func TestWindowsSkillMetadataRejectsBroadDirectory(t *testing.T) {
	for _, operation := range []string{"directory", "publish", "replace"} {
		t.Run(operation, func(t *testing.T) {
			root := filepath.Join(t.TempDir(), "private")
			if err := privatefs.MkdirAll(root); err != nil {
				t.Fatal(err)
			}
			acltest.BroadenRead(t, root, root)
			path := filepath.Join(root, "metadata.json")
			var err error
			switch operation {
			case "directory":
				err = privateDirectory(root)
			case "publish":
				err = publishDocument(path, map[string]any{"fixture": "metadata"})
			case "replace":
				err = replaceDocument(path, map[string]any{"fixture": "metadata"})
			}
			if err == nil {
				t.Error("broad metadata directory accepted")
			}
			if _, err := os.Lstat(path); !os.IsNotExist(err) {
				t.Error("rejected metadata exposed")
			}
			if privatefs.CheckDir(root) == nil {
				t.Fatal("wide directory repaired")
			}
		})
	}
}

func TestWindowsSkillScheduleRejectsBroadExistingFile(t *testing.T) {
	root := filepath.Join(t.TempDir(), "private")
	if err := privatefs.MkdirAll(root); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "schedule.json")
	if err := replaceDocument(path, map[string]any{"fixture": "original"}); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	acltest.BroadenRead(t, root, path)
	if err := replaceDocument(path, map[string]any{"fixture": "replacement"}); err == nil {
		t.Error("wide schedule replaced")
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(before, after) {
		t.Error("wide schedule bytes changed")
	}
	if privatefs.CheckFilePath(path) == nil {
		t.Error("wide schedule ACL repaired")
	}
}

func TestWindowsSkillOpenRejectsBroadStateWithoutWrites(t *testing.T) {
	f := setup(t)
	s := f.store
	before, err := os.ReadDir(s.dir)
	if err != nil {
		t.Fatal(err)
	}
	restore := acltest.BroadenRead(t, s.authority.Dir, s.authority.Dir)
	if _, err := Open(s.authority, s.key, s.imports, s.resolve); err == nil {
		t.Error("broad state accepted by new store")
	}
	after, err := os.ReadDir(s.dir)
	if err != nil || len(before) != len(after) {
		t.Fatal("rejected open changed metadata directory")
	}
	if privatefs.CheckDir(s.authority.Dir) == nil {
		t.Fatal("state ACL repaired")
	}
	restore()
	if _, err := Open(s.authority, s.key, s.imports, s.resolve); err != nil {
		t.Fatal("restored fixture rejected", err)
	}
}

func TestWindowsSkillMetadataPublicationIsPrivateAndExclusive(t *testing.T) {
	root := filepath.Join(t.TempDir(), "private")
	path := filepath.Join(root, "operation.json")
	if err := publishDocument(path, map[string]any{"fixture": "first"}); err != nil {
		t.Fatal(err)
	}
	if err := privatefs.CheckDir(root); err != nil {
		t.Fatal("published parent is not private", err)
	}
	if err := privatefs.CheckFilePath(path); err != nil {
		t.Fatal("published file is not private and single-linked", err)
	}
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 1 {
		t.Fatal("successful publication retained scratch", err)
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := publishDocument(path, map[string]any{"fixture": "second"}); !errors.Is(err, ErrConflict) {
		t.Fatal("publication did not reject collision", err)
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("collision changed original", err)
	}
	// Schedule replacement is separately authorized and must retain privacy.
	if err := replaceDocument(path, map[string]any{"fixture": "replacement"}); err != nil {
		t.Fatal(err)
	}
	after, err = os.ReadFile(path)
	if err != nil || bytes.Equal(before, after) {
		t.Fatal("explicit replacement did not update schedule", err)
	}
	if err := privatefs.CheckFilePath(path); err != nil {
		t.Fatal("replacement is not private and single-linked", err)
	}
}
