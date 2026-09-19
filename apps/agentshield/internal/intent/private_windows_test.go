package intent

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/privatefs"
)

func TestWindowsIntentPrivateReadAndCachedStore(t *testing.T) {
	s := testStore(t)
	c, err := s.Issue(testContract())
	if err != nil {
		t.Fatal(err)
	}
	p, _ := s.path(c.IntentID)
	before, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	for _, kind := range []string{"file", "directory", "state"} {
		t.Run(kind, func(t *testing.T) {
			target := p
			if kind == "directory" {
				target = s.dir
			}
			if kind == "state" {
				target = filepath.Dir(s.dir)
			}
			restore := acltest.BroadenRead(t, filepath.Dir(s.dir), target)
			if _, err := s.Get(c.IntentID); err == nil || errors.Is(err, os.ErrNotExist) {
				t.Error("unsafe authority accepted or treated as missing", err)
			}
			if _, err := s.List(); err == nil {
				t.Error("unsafe authority enumerated")
			}
			after, err := os.ReadFile(p)
			if err != nil || !bytes.Equal(before, after) {
				t.Fatal("authority bytes changed")
			}
			restore()
			if _, err := s.Get(c.IntentID); err != nil {
				t.Fatal("restored fixture rejected", err)
			}
		})
	}
}

func TestWindowsIntentUnsafeRevocationDirectoryIsNotAbsence(t *testing.T) {
	s := testStore(t)
	c, err := s.Issue(testContract())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.Bind(Binding{Platform: "hermes", SessionID: "s1", AgentID: "a-1", IntentID: c.IntentID}); err != nil {
		t.Fatal(err)
	}
	for _, dir := range []string{s.revocationDir(), s.intentRevocationDir(), s.bindingDir()} {
		t.Run(filepath.Base(dir), func(t *testing.T) {
			restore := acltest.BroadenRead(t, filepath.Dir(s.dir), dir)
			if _, _, err := s.ResolveBinding("hermes", "s1", "a-1"); err == nil || errors.Is(err, os.ErrNotExist) {
				t.Error("unsafe directory became absent revocation or valid binding", err)
			}
			if privatefs.CheckDir(dir) == nil {
				t.Error("directory ACL repaired")
			}
			restore()
			if _, _, err := s.ResolveBinding("hermes", "s1", "a-1"); err != nil {
				t.Fatal("restored binding rejected", err)
			}
		})
	}
}

func TestWindowsIntentMissingRevocationDirectoryDenies(t *testing.T) {
	s := testStore(t)
	c, err := s.Issue(testContract())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.Bind(Binding{Platform: "hermes", SessionID: "s1", AgentID: "a-1", IntentID: c.IntentID}); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(s.revocationDir()); err != nil {
		t.Fatal(err)
	}
	if _, _, err := s.ResolveBinding("hermes", "s1", "a-1"); err == nil || errors.Is(err, os.ErrNotExist) {
		t.Fatal("missing revocation directory treated as missing record", err)
	}
}

func TestWindowsIntentPublishAndOpenRejectBroadDirectory(t *testing.T) {
	s := testStore(t)
	for _, dir := range []string{s.dir, s.bindingDir(), s.revocationDir(), s.intentRevocationDir(), s.contextDir()} {
		t.Run(filepath.Base(dir), func(t *testing.T) {
			restore := acltest.BroadenRead(t, filepath.Dir(s.dir), dir)
			p := filepath.Join(dir, "new.json")
			if err := publish(p, []byte(`{"fixture":true}`)); err == nil {
				t.Error("published in unsafe directory")
			}
			if _, err := os.Stat(p); !os.IsNotExist(err) {
				t.Error("rejected publish exposed record")
			}
			if _, err := Open(filepath.Dir(s.dir), s.key); err == nil {
				t.Error("reopened unsafe directory")
			}
			if privatefs.CheckDir(dir) == nil {
				t.Error("ACL repaired")
			}
			restore()
		})
	}
}

func TestWindowsIntentRetryDoesNotAccumulatePrivateScratch(t *testing.T) {
	s := testStore(t)
	first, err := s.Issue(testContract())
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		again, err := s.Issue(testContract())
		if err != nil || again.Signature != first.Signature {
			t.Fatal("retry changed authority", err)
		}
	}
	entries, err := os.ReadDir(s.dir)
	if err != nil || len(entries) != 1 {
		t.Fatal("idempotent retry accumulated scratch", len(entries), err)
	}
	path, _ := s.path(first.IntentID)
	if err := privatefs.CheckFilePath(path); err != nil {
		t.Fatal("published authority is not private and single-linked", err)
	}
}
