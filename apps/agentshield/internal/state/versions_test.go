package state

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestVersionProcessWorker(t *testing.T) {
	dir := os.Getenv("SIQ_TEST_VERSION_DIR")
	if dir == "" {
		return
	}
	st := &Store{Dir: dir}
	for i := 0; i < 20; i++ {
		g := grant.Grant{GrantID: "process", Status: fmt.Sprintf("%s-%d", os.Getenv("SIQ_TEST_VERSION_WORKER"), i)}
		if err := st.PutGrant(g); err != nil {
			t.Fatal(err)
		}
	}
}

func TestIndependentProcessesPublishUniqueVersions(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	var wg sync.WaitGroup
	for worker := 0; worker < 4; worker++ {
		wg.Add(1)
		go func(worker int) {
			defer wg.Done()
			cmd := exec.CommandContext(ctx, exe, "-test.run=^TestVersionProcessWorker$")
			cmd.Env = append(os.Environ(), "SIQ_TEST_VERSION_DIR="+st.Dir, fmt.Sprintf("SIQ_TEST_VERSION_WORKER=%d", worker))
			if out, err := cmd.CombinedOutput(); err != nil {
				t.Errorf("worker %d: %v: %s", worker, err, out)
			}
		}(worker)
	}
	wg.Wait()
	entries, err := os.ReadDir(filepath.Join(st.Dir, "grants"))
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 80 {
		t.Fatalf("80 successful process writes require 80 versions, got %d", len(entries))
	}
	seen := map[string]bool{}
	for _, entry := range entries {
		raw, err := os.ReadFile(filepath.Join(st.Dir, "grants", entry.Name()))
		if err != nil {
			t.Fatal(err)
		}
		var g grant.Grant
		if err := json.Unmarshal(raw, &g); err != nil {
			t.Fatal(err)
		}
		if seen[g.Status] {
			t.Fatalf("duplicate content %s", g.Status)
		}
		seen[g.Status] = true
	}
}

func TestMalformedLatestGrantIsAnError(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := st.PutGrant(grant.Grant{GrantID: "broken", Status: "effective"}); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(st.Dir, "grants", "broken.1.json"), []byte(`{"status":`), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := st.ListGrants(); err == nil {
		t.Fatal("corrupt latest grant must not become an empty successful list or expose the old grant")
	}
}

func TestGrantIdentityMustMatchVersionFilename(t *testing.T) {
	for _, raw := range []string{"null", "{}", `{"grant_id":"other","status":"effective"}`} {
		t.Run(raw, func(t *testing.T) {
			st, err := Open(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(st.Dir, "grants", "expected.0.json"), []byte(raw), 0o600); err != nil {
				t.Fatal(err)
			}
			if _, err := st.ListGrants(); err == nil {
				t.Fatal("invalid identity treated as a successful grant list")
			}
		})
	}
}

func TestConcurrentVersionsPreserveEverySuccessfulWrite(t *testing.T) {
	for _, kind := range []string{"grants", "assets"} {
		t.Run(kind, func(t *testing.T) {
			st, err := Open(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			const count = 100
			start := make(chan struct{})
			errs := make(chan error, count)
			var wg sync.WaitGroup
			for i := 0; i < count; i++ {
				wg.Add(1)
				go func(i int) {
					defer wg.Done()
					<-start
					// Distinct Store instances share only the filesystem.
					writer := &Store{Dir: st.Dir}
					g := grant.Grant{GrantID: "concurrent", Status: fmt.Sprint(i)}
					if kind == "grants" {
						errs <- writer.PutGrant(g)
					} else {
						errs <- writer.PutVersioned(kind, g.GrantID, g)
					}
				}(i)
			}
			close(start)
			wg.Wait()
			close(errs)
			for err := range errs {
				if err != nil {
					t.Fatal(err)
				}
			}
			seen := map[string]bool{}
			for i := 0; i < count; i++ {
				raw, err := os.ReadFile(filepath.Join(st.Dir, kind, fmt.Sprintf("concurrent.%d.json", i)))
				if err != nil {
					t.Fatalf("successful version %d missing: %v", i, err)
				}
				var g grant.Grant
				if err := json.Unmarshal(raw, &g); err != nil {
					t.Fatal(err)
				}
				if seen[g.Status] {
					t.Fatalf("duplicated content %s", g.Status)
				}
				seen[g.Status] = true
			}
			if len(seen) != count {
				t.Fatalf("persisted %d of %d", len(seen), count)
			}
		})
	}
}

func TestWriteNewConflictIsNotSuccess(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(st.Dir, "evidence", "ev-same.json")
	if err := writeNew(path, []byte(`{"id":"a"}`)); err != nil {
		t.Fatal(err)
	}
	if err := writeNew(path, []byte(`{"id":"a"}`)); err != nil {
		t.Fatalf("identical content must be idempotent: %v", err)
	}
	if err := writeNew(path, []byte(`{"id":"b"}`)); err == nil {
		t.Fatal("different content on an existing id was treated as success")
	}
	raw, err := os.ReadFile(path)
	if err != nil || string(raw) != `{"id":"a"}` {
		t.Fatalf("existing document mutated: %s %v", raw, err)
	}
}

func TestVersionedWritePreservesPreviousVersion(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	for _, state := range []string{"pending", "approved"} {
		if err := st.PutVersioned("assets", "item", map[string]string{"state": state}); err != nil {
			t.Fatal(err)
		}
	}
	for i, want := range []string{"pending", "approved"} {
		raw, err := os.ReadFile(filepath.Join(st.Dir, "assets", fmt.Sprintf("item.%d.json", i)))
		if err != nil {
			t.Fatal(err)
		}
		var got map[string]string
		if err := json.Unmarshal(raw, &got); err != nil {
			t.Fatal(err)
		}
		if got["state"] != want {
			t.Fatalf("version %d overwritten: %v", i, got)
		}
	}
	if err := st.PutVersioned("assets", "bad", make(chan int)); err == nil {
		t.Fatal("unserializable document accepted")
	}
	if _, err := os.Stat(filepath.Join(st.Dir, "assets", "bad.0.json")); !os.IsNotExist(err) {
		t.Fatalf("failed serialization published a version: %v", err)
	}
}
