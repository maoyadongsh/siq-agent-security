package skillcontext

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestInvocationHistoryPagesAndRevocationRemainHistorical(t *testing.T) {
	f := newInvocationStoreFixture(t)
	contexts := map[string]*InvocationContext{}
	for i := 1; i <= 5; i++ {
		c := f.issueV2(f.request(i, nil))
		contexts[c.ContextID] = c
	}
	var original *InvocationContext
	for _, c := range contexts {
		original = c
		break
	}
	rev, err := f.s.Revoke(original.ContextID, original.Signature)
	if err != nil {
		t.Fatal(err)
	}
	// Grant removal and time passage affect execution, not signed-history reads.
	delete(f.grants, testGrantID)
	f.now = f.now.Add(2 * time.Hour)
	seen, after := map[string]bool{}, ""
	for pageNumber := 0; ; pageNumber++ {
		if pageNumber > 3 {
			t.Fatal("pagination did not terminate")
		}
		page, err := f.s.ListHistory(context.Background(), testInstall, testSession, after, 2)
		if err != nil || len(page.Contexts) > 2 {
			t.Fatal(page, err)
		}
		for _, row := range page.Contexts {
			id := row.Context.ContextID
			if seen[id] || id <= after || !reflect.DeepEqual(row.Context, contexts[id]) {
				t.Fatal("repeated, unordered, or changed history")
			}
			seen[id] = true
			if id == original.ContextID && !reflect.DeepEqual(row.Revocation, rev) {
				t.Fatal("missing signed tombstone")
			}
		}
		if page.NextAfter == "" {
			break
		}
		after = page.NextAfter
	}
	if len(seen) != 5 {
		t.Fatal("history lost")
	}
	for _, query := range [][2]string{{"other-install", ""}, {testInstall, "other-session"}} {
		page, err := f.s.ListHistory(context.Background(), query[0], query[1], "", 64)
		if err != nil || len(page.Contexts) != 0 || page.NextAfter != "" {
			t.Fatal("scope filter", page, err)
		}
	}
	restarted, err := OpenInvocations(f.s.dir, f.s.deps)
	if err != nil {
		t.Fatal(err)
	}
	r, err := restarted.ReadHistory(context.Background(), original.ContextID)
	if err != nil || !reflect.DeepEqual(r.Revocation, rev) {
		t.Fatal("restart read", r, err)
	}
}

func TestInvocationHistoryRejectsCorruptionAndCancellation(t *testing.T) {
	for _, fault := range []string{"context", "revocation", "entry", "symlink"} {
		t.Run(fault, func(t *testing.T) {
			f := newInvocationStoreFixture(t)
			c := f.issueV2(f.request(1, nil))
			switch fault {
			case "context":
				c.Subject.TaskID = "tampered"
				raw, _ := json.Marshal(c)
				if err := os.WriteFile(f.s.contextPath(c.ContextID), raw, 0600); err != nil {
					t.Fatal(err)
				}
			case "revocation":
				if _, err := f.s.Revoke(c.ContextID, c.Signature); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(f.s.revokedPath(c.ContextID), []byte("{}"), 0600); err != nil {
					t.Fatal(err)
				}
			case "entry":
				if err := os.WriteFile(filepath.Join(f.s.contextDir(), "unrecognized"), []byte("{}"), 0600); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				if err := os.Symlink(f.s.contextPath(c.ContextID), filepath.Join(f.s.contextDir(), "sec-"+strings.Repeat("f", 32)+".json")); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := f.s.ListHistory(context.Background(), testInstall, "", "", 32); err == nil {
				t.Fatal("corrupt history accepted")
			}
		})
	}
	f := newInvocationStoreFixture(t)
	c := f.issueV2(f.request(1, nil))
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := f.s.ReadHistory(ctx, c.ContextID); err != context.Canceled {
		t.Fatal(err)
	}
	// A queued history request must expire even while publication holds the lock.
	mu.Lock()
	ctx, cancel = context.WithTimeout(context.Background(), 20*time.Millisecond)
	_, err := f.s.ListHistory(ctx, testInstall, "", "", 32)
	cancel()
	mu.Unlock()
	if err != context.DeadlineExceeded {
		t.Fatal(err)
	}
}

func TestInvocationHistoryInputAndRevokeVersionBoundaries(t *testing.T) {
	f := newInvocationStoreFixture(t)
	for _, limit := range []int{-1, 0, 65} {
		if _, err := f.s.ListHistory(context.Background(), testInstall, "", "", limit); err == nil {
			t.Fatal(limit)
		}
	}
	for _, query := range [][3]string{{"", "", ""}, {testInstall, "bad\x00session", ""}, {testInstall, "", "../other"}} {
		if _, err := f.s.ListHistory(context.Background(), query[0], query[1], query[2], 32); err == nil {
			t.Fatal(query)
		}
	}
	r := InvocationRevokeRequest{SchemaVersion: InvocationRevokeRequestSchema, ExpectedContextSignature: strings.Repeat("a", 128), ActorID: "operator", ConfirmRevoke: true}
	if !r.Valid() {
		t.Fatal("valid request rejected")
	}
	r.SchemaVersion = RevokeRequestSchema
	if r.Valid() {
		t.Fatal("v1 request accepted")
	}
}

func TestInvocationManagementContractSamples(t *testing.T) {
	for name, target := range map[string]any{
		"local-skill-context-management-v2.sample.json":       &InvocationPage{},
		"local-skill-execution-context-revoke-v2.sample.json": &InvocationRevokeRequest{},
	} {
		raw, err := os.ReadFile(filepath.Join("../../testdata/contracts", name))
		if err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(raw, target); err != nil {
			t.Fatal(err)
		}
		got, err := json.Marshal(target)
		if err != nil {
			t.Fatal(err)
		}
		var expected, actual any
		if json.Unmarshal(raw, &expected) != nil || json.Unmarshal(got, &actual) != nil || !reflect.DeepEqual(expected, actual) {
			t.Fatal("Go management wire format differs from independently validated contract", name)
		}
	}
}
