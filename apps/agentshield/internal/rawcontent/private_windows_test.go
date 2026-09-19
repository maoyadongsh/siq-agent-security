package rawcontent

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/acltest"
)

func TestWindowsRawContentCachedKeyRejectsACLDrift(t *testing.T) {
	for _, scope := range []string{"root", "keys", "key", "content"} {
		t.Run(scope, func(t *testing.T) {
			root := t.TempDir()
			s, err := Initialize(root, Limits{Retention: DefaultRetention, Budget: DefaultBudget})
			if err != nil {
				t.Fatal(err)
			}
			p, err := Prepare("input", []Field{{Path: "/prompt", Value: "public fixture"}})
			if err != nil {
				t.Fatal(err)
			}
			now := time.Now().UTC()
			e, err := s.write("fixture-task", p, DefaultRetention, now)
			if err != nil {
				t.Fatal(err)
			}
			path := root
			if scope == "keys" {
				path = filepath.Join(root, "keys")
			}
			if scope == "key" {
				path = keyPath(root)
			}
			if scope == "content" {
				path = filepath.Join(s.dir, e.RecordID+".json")
			}
			restore := acltest.BroadenRead(t, root, path)
			before, err := os.ReadDir(s.dir)
			if err != nil {
				t.Fatal(err)
			}
			if fields, _, err := s.Read("fixture-task", e.RecordID, now); err == nil || len(fields) != 0 {
				t.Fatal("cached key decrypted unsafe state")
			}
			if scope != "content" {
				if _, err := s.write("fixture-task", p, DefaultRetention, now); err == nil {
					t.Fatal("cached key wrote after ACL drift")
				}
			}
			after, err := os.ReadDir(s.dir)
			if err != nil || len(after) != len(before) {
				t.Fatal("rejected operation created content")
			}
			restore()
			if fields, _, err := s.Read("fixture-task", e.RecordID, now); err != nil || len(fields) != 1 {
				t.Fatal("restored fixture rejected", err)
			}
		})
	}
}

func TestWindowsRawContentCachedKeyRejectsMissingOrChangedKey(t *testing.T) {
	for _, remove := range []bool{false, true} {
		t.Run(map[bool]string{false: "changed", true: "missing"}[remove], func(t *testing.T) {
			root := t.TempDir()
			s, err := Initialize(root, Limits{Retention: DefaultRetention, Budget: DefaultBudget})
			if err != nil {
				t.Fatal(err)
			}
			p, _ := Prepare("input", []Field{{Path: "/prompt", Value: "public fixture"}})
			e, err := s.write("fixture-task", p, DefaultRetention, time.Now().UTC())
			if err != nil {
				t.Fatal(err)
			}
			if remove {
				err = os.Remove(keyPath(root))
			} else {
				err = os.WriteFile(keyPath(root), []byte("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="), 0600)
			}
			if err != nil {
				t.Fatal(err)
			}
			if _, _, err := s.Read("fixture-task", e.RecordID, time.Now().UTC()); err == nil {
				t.Fatal("cached key survived storage change")
			}
			if _, err := s.write("fixture-task", p, DefaultRetention, time.Now().UTC()); err == nil {
				t.Fatal("cached key created content after storage change")
			}
		})
	}
}
