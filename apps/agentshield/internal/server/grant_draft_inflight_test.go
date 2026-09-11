package server

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/state"
)

// Drive the real HTTP route and real Store publication window. The writer stays
// parked until the second handler itself reports a real ErrIncompleteCommit;
// elapsed time or an unscheduled goroutine cannot stand in for that event.
// Restoring the pre-fix 409 branch returns before this observation and fails the
// same test. Timeouts are failure exits only, never evidence of progress.
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

	entered, release, duplicateRead := make(chan struct{}), make(chan struct{}), make(chan struct{})
	var enteredOnce, releaseOnce, readOnce sync.Once
	releaseWriter := func() { releaseOnce.Do(func() { close(release) }) }
	restoreCommit := state.SetCommitBoundaryHook(func(phase string) {
		if phase == "grant" {
			enteredOnce.Do(func() { close(entered) })
			<-release
		}
	})
	previousReadHook := grantDraftIncompleteRead
	grantDraftIncompleteRead = func() { readOnce.Do(func() { close(duplicateRead) }) }

	type reply struct {
		code int
		out  map[string]any
	}
	type flight struct {
		result   chan reply
		finished chan struct{}
	}
	var requests []*flight
	callAsync := func() *flight {
		f := &flight{result: make(chan reply, 1), finished: make(chan struct{})}
		requests = append(requests, f)
		go func() {
			defer close(f.finished)
			code, out := call(t, s, "POST", route, token, body)
			f.result <- reply{code, out}
		}()
		return f
	}
	recv := func(f *flight, what string) reply {
		t.Helper()
		select {
		case r := <-f.result:
			return r
		case <-time.After(30 * time.Second):
			t.Fatalf("timeout waiting for %s", what)
			return reply{}
		}
	}
	defer func() {
		// Release on every failure, then join BOTH handlers, including one whose
		// result was already consumed. Never rewrite a hook still in use.
		releaseWriter()
		allFinished := true
		for i, f := range requests {
			select {
			case <-f.finished:
			case <-time.After(30 * time.Second):
				allFinished = false
				t.Errorf("request %d did not finish during cleanup", i+1)
			}
		}
		if allFinished {
			grantDraftIncompleteRead = previousReadHook
			restoreCommit()
		}
	}()

	winner := callAsync()
	select {
	case <-entered:
	case <-time.After(30 * time.Second):
		t.Fatal("winner never reached the publication window")
	}
	if _, _, err := store.GetGrantWithSeq(draftID); !errors.Is(err, state.ErrIncompleteCommit) {
		t.Fatalf("window read = %v, want ErrIncompleteCommit", err)
	}

	duplicate := callAsync()
	select {
	case r := <-duplicate.result:
		t.Fatalf("duplicate returned inside the window instead of waiting: %d %v", r.code, r.out)
	case <-duplicateRead:
		// Emitted by the handler AFTER its own actual Store read, while the
		// winner is still parked. This is not the test's earlier self-read.
	case <-time.After(30 * time.Second):
		t.Fatal("duplicate never observed the incomplete publication window")
	}
	select {
	case r := <-duplicate.result:
		t.Fatalf("duplicate returned inside the window instead of waiting: %d %v", r.code, r.out)
	default:
	}

	releaseWriter()
	w := recv(winner, "winner")
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
