package server

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/state"
)

// The store publishes a commit's grant file before its done marker, so a reader
// racing a real commit can observe ErrIncompleteCommit. The draft route must
// wait out that window via the serialized commit path instead of failing with
// 409. This drives the actual HTTP handler twice through that window with the
// writer parked on the test-only commit boundary hook:
//
//  1. request 1 (winner) commits and is paused after the grant file is
//     published but before the done marker (commitBoundary "grant" phase);
//  2. the test itself reads the store and must see ErrIncompleteCommit, proving
//     the window is really open;
//  3. request 2 (duplicate) is issued only after the window is observed open; it
//     must not return while the window is held — under the repaired handler its
//     only parking point is the commit lock, which it can reach only after its
//     read returned ErrIncompleteCommit;
//  4. releasing the writer must converge both requests on the same draft.
//
// A handler that answers ErrIncompleteCommit with an immediate 409 (the pre-fix
// behavior) makes request 2 return during step 3, failing this test
// deterministically. Timeouts only bound failure exits; progress is
// channel-synchronized.
func TestGrantDraftHTTPInflightWriterConverges(t *testing.T) {
	s, store, id, rev := draftSource(t)
	source, _, err := store.GetGrantWithSeq(id)
	if err != nil {
		t.Fatal(err)
	}
	before, _ := json.Marshal(source)
	route := "/v1/grants/" + id + "/draft"
	body := draftBody(rev)
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%d\x00%s\x00%s", id, rev, "operator", "gd-"+strings.Repeat("a", 32))))
	draftID := "grt-d-" + hex.EncodeToString(digest[:])

	entered := make(chan struct{})
	release := make(chan struct{})
	restore := state.SetCommitBoundaryHook(func(phase string) {
		if phase == "grant" {
			close(entered)
			<-release
		}
	})

	type reply struct {
		code int
		out  map[string]any
	}
	callAsync := func() chan reply {
		ch := make(chan reply, 1)
		go func() {
			code, out := call(t, s, "POST", route, token, body)
			ch <- reply{code, out}
		}()
		return ch
	}
	recv := func(ch chan reply, what string) reply {
		t.Helper()
		select {
		case r := <-ch:
			return r
		case <-time.After(30 * time.Second):
			t.Fatalf("timeout waiting for %s", what)
			return reply{}
		}
	}

	released := false
	winnerReceived := false
	winner := callAsync()
	defer func() {
		// Failure exit must release a parked writer and drain it before the hook
		// is restored; the hook is never rewritten while a commit may use it.
		if !released {
			close(release)
		}
		if !winnerReceived {
			select {
			case <-winner:
			case <-time.After(30 * time.Second):
				t.Error("writer did not finish during cleanup")
			}
		}
		restore()
	}()

	select {
	case <-entered:
	case <-time.After(30 * time.Second):
		t.Fatal("winner never reached the publication window")
	}
	// The window is real: the draft file is published, its done marker is not.
	if _, _, err := store.GetGrantWithSeq(draftID); !errors.Is(err, state.ErrIncompleteCommit) {
		t.Fatalf("window read = %v, want ErrIncompleteCommit", err)
	}

	duplicate := callAsync()
	select {
	case r := <-duplicate:
		t.Fatalf("duplicate returned inside the window instead of waiting: %d %v", r.code, r.out)
	case <-time.After(250 * time.Millisecond):
	}

	close(release)
	released = true
	w := recv(winner, "winner")
	winnerReceived = true
	d := recv(duplicate, "duplicate")
	if w.code != 200 || d.code != 200 {
		t.Fatalf("winner=%d %v duplicate=%d %v", w.code, w.out, d.code, d.out)
	}
	if w.out["reused"] != false || d.out["reused"] != true {
		t.Fatalf("expected create-then-reuse: %v %v", w.out["reused"], d.out["reused"])
	}
	for name, r := range map[string]reply{"winner": w, "duplicate": d} {
		if got := r.out["grant"].(map[string]any)["grant_id"]; got != draftID {
			t.Fatalf("%s grant_id %v != %s", name, got, draftID)
		}
	}
	created, seq, err := store.GetGrantWithSeq(draftID)
	if err != nil || seq != 0 || created.Status != "pending_approval" || !grant.Verify(s.d.Key.Public(), *created) {
		t.Fatal(seq, err, created)
	}
	source, sourceRev, _ := store.GetGrantWithSeq(id)
	after, _ := json.Marshal(source)
	if sourceRev != rev || string(before) != string(after) {
		t.Fatal("source modified")
	}
	events, err := store.TailAudit(100)
	if err != nil {
		t.Fatal(err)
	}
	drafts := 0
	for _, e := range events {
		if e.Event == "grant_draft" {
			drafts++
			if e.Target != draftID {
				t.Fatal("unexpected draft audit target", e)
			}
		}
	}
	if drafts != 1 {
		t.Fatal("duplicate draft audit", drafts)
	}
}
