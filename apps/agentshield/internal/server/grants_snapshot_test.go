package server

import (
	"crypto/sha256"
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/state"
)

func grantsSnapshotHTTP(t *testing.T, s *Server) (*httptest.ResponseRecorder, map[string]json.RawMessage) {
	t.Helper()
	req := loopbackRequest("GET", "/v1/grants", nil)
	req.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	var body map[string]json.RawMessage
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatal("invalid list JSON", err)
	}
	return w, body
}

// Only immutable Grant transaction material is captured, not tokens or keys.
func grantSnapshotFiles(t *testing.T, dir string) map[string][32]byte {
	t.Helper()
	out := map[string][32]byte{}
	for _, name := range []string{"grants", "commits", "commit-audit"} {
		entries, err := os.ReadDir(filepath.Join(dir, name))
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			t.Fatal(err)
		}
		out[name+"/"] = sha256.Sum256(nil)
		for _, e := range entries {
			if e.IsDir() {
				continue
			}
			rel := filepath.Join(name, e.Name())
			raw, err := os.ReadFile(filepath.Join(dir, rel))
			if err != nil {
				t.Fatal(err)
			}
			out[rel] = sha256.Sum256(raw)
		}
	}
	return out
}

func TestGrantsSnapshotHTTPActiveCommitBusyThenExactRevision(t *testing.T) {
	for _, action := range []string{"approve", "revoke"} {
		for _, boundary := range []string{"prepared", "grant"} {
			t.Run(action+"/"+boundary, func(t *testing.T) {
				s, store, id, rev := expiryFixture(t)
				route := "/v1/grants/" + id
				body := map[string]any{"actor_id": "snapshot-operator", "expected_revision": rev}
				if action == "approve" {
					code, out := call(t, s, "POST", route+"/challenge", token, withRevision(nil, rev))
					if code != 200 {
						t.Fatal(code, out)
					}
					ch := out["challenge"].(map[string]any)
					body["challenge_id"], body["nonce"] = ch["challenge_id"], ch["nonce"]
				} else {
					code, approved := approveChallenged(t, s, id, "snapshot-operator", rev)
					if code != 200 {
						t.Fatal(code, approved)
					}
					code, deployed := call(t, s, "POST", route+"/deploy", token, withRevision(map[string]any{"actor_id": "snapshot-operator"}, stateRevision(t, approved)))
					if code != 200 {
						t.Fatal(code, deployed)
					}
					rev = stateRevision(t, deployed)
					body["expected_revision"] = rev
					if store.ActiveGrant("hermes", "expiry-agent") == nil {
						t.Fatal("missing revoke positive control")
					}
				}
				entered, release, finished := make(chan struct{}), make(chan struct{}), make(chan struct{})
				var once, releaseOnce sync.Once
				releaseWriter := func() { releaseOnce.Do(func() { close(release) }) }
				restore := state.SetCommitBoundaryHook(func(phase string) {
					if phase == boundary {
						once.Do(func() { close(entered) })
						<-release
					}
				})
				var code int
				var written map[string]any
				go func() { defer close(finished); code, written = call(t, s, "POST", route+"/"+action, token, body) }()
				defer func() {
					releaseWriter()
					select {
					case <-finished:
						restore()
					case <-time.After(30 * time.Second):
						t.Error("writer did not finish; hook not reset")
					}
				}()
				select {
				case <-entered:
				case <-finished:
					t.Fatalf("writer ended before boundary: %d", code)
				case <-time.After(30 * time.Second):
					t.Fatal("writer did not reach boundary")
				}
				before := grantSnapshotFiles(t, store.Dir)
				w, listed := grantsSnapshotHTTP(t, s)
				if w.Code != 503 || w.Header().Get("Retry-After") != "1" || string(listed["error"]) != `"grants_busy"` || len(listed) != 1 {
					t.Fatalf("active commit list: status=%d body=%s", w.Code, w.Body.String())
				}
				if !reflect.DeepEqual(before, grantSnapshotFiles(t, store.Dir)) {
					t.Fatal("GET changed transaction files")
				}
				if action == "revoke" && store.ActiveGrant("hermes", "expiry-agent") != nil {
					t.Fatal("incomplete revoke exposed old grant")
				}
				releaseWriter()
				select {
				case <-finished:
				case <-time.After(30 * time.Second):
					t.Fatal("writer did not finish")
				}
				if code != 200 || stateRevision(t, written) != rev+1 {
					t.Fatal("write did not settle", code)
				}
				current, seq, err := store.GetGrantWithSeq(id)
				if err != nil || seq != rev+1 || !grant.Verify(s.d.Key.Public(), *current) {
					t.Fatal("invalid committed result", err)
				}
				w, listed = grantsSnapshotHTTP(t, s)
				var values []grant.Grant
				var revisions map[string]int
				if w.Code != 200 || json.Unmarshal(listed["grants"], &values) != nil || json.Unmarshal(listed["state_revisions"], &revisions) != nil || len(values) != 1 || len(revisions) != 1 || revisions[id] != seq || values[0].Signature != current.Signature {
					t.Fatal("list did not return exact committed content and revision")
				}
				if action == "revoke" && store.ActiveGrant("hermes", "expiry-agent") != nil {
					t.Fatal("revoked grant remained selected")
				}
			})
		}
	}
}

func TestGrantsSnapshotHTTPPersistentDamageIsNotBusy(t *testing.T) {
	for _, damage := range []string{"orphan_initial_prepare", "corrupt_latest", "bad_done_digest"} {
		t.Run(damage, func(t *testing.T) {
			s, store := newServer(t, "block")
			c := state.GrantCommit{Grant: grant.Grant{GrantID: "snapshot-fixture", Status: "pending_approval"}, ExpectedRevision: -1}
			switch damage {
			case "orphan_initial_prepare":
				c.DesiredPolicy = grant.DesiredPolicy{"policy_id": "blocked-policy", "version": 1}
				if err := os.Mkdir(filepath.Join(store.Dir, "policies", "blocked-policy.v1.json"), 0700); err != nil {
					t.Fatal(err)
				}
				if _, err := store.CommitGrant(c); err == nil {
					t.Fatal("expected publication failure")
				}
			case "corrupt_latest":
				if _, err := store.CommitGrant(c); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(store.Dir, "grants", "snapshot-fixture.1.json"), []byte(`{"status":`), 0600); err != nil {
					t.Fatal(err)
				}
			case "bad_done_digest":
				if _, err := store.CommitGrant(c); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join(store.Dir, "commits", "snapshot-fixture.0.done.json"), []byte("bad\n"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			before := grantSnapshotFiles(t, store.Dir)
			w, body := grantsSnapshotHTTP(t, s)
			if w.Code != 500 || string(body["error"]) != `"store unreadable"` || len(body) != 1 || w.Header().Get("Retry-After") != "" {
				t.Fatal("persistent damage became busy or successful", w.Code)
			}
			if !reflect.DeepEqual(before, grantSnapshotFiles(t, store.Dir)) {
				t.Fatal("GET repaired or changed damaged state")
			}
		})
	}
}
