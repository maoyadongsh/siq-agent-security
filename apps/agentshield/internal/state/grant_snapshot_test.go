package state

import (
	"encoding/json"
	"errors"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
)

type pausedGrantDocument struct {
	value            grant.Grant
	entered, release chan struct{}
}

func (d pausedGrantDocument) MarshalJSON() ([]byte, error) {
	close(d.entered)
	<-d.release
	return json.Marshal(d.value)
}

func TestGrantSnapshotVersionWritersAreBusyAcrossStores(t *testing.T) {
	for _, cas := range []bool{false, true} {
		name := "ordinary"
		if cas {
			name = "cas"
		}
		t.Run(name, func(t *testing.T) {
			store, err := Open(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			reader := &Store{Dir: store.Dir}
			other, err := Open(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			entered, release, finished := make(chan struct{}), make(chan struct{}), make(chan struct{})
			var once sync.Once
			releaseWriter := func() { once.Do(func() { close(release) }) }
			doc := pausedGrantDocument{grant.Grant{GrantID: "snapshot-first", Status: "pending_approval"}, entered, release}
			var writeErr error
			go func() {
				defer close(finished)
				if cas {
					_, writeErr = store.PutVersionedCAS("grants", doc.value.GrantID, -1, doc)
				} else {
					writeErr = store.PutVersioned("grants", doc.value.GrantID, doc)
				}
			}()
			defer func() {
				releaseWriter()
				select {
				case <-finished:
				case <-time.After(30 * time.Second):
					t.Error("writer did not finish")
				}
			}()
			select {
			case <-entered:
			case <-finished:
				t.Fatal("writer did not reach marshalling", writeErr)
			case <-time.After(30 * time.Second):
				t.Fatal("writer did not start")
			}
			if values, revisions, err := reader.ListGrantsWithRevisions(); !errors.Is(err, ErrGrantsBusy) || values != nil || revisions != nil {
				t.Fatal("separate Store bypassed active publication", err)
			}
			if values, revisions, err := other.ListGrantsWithRevisions(); err != nil || values == nil || len(values) != 0 || revisions == nil || len(revisions) != 0 {
				t.Fatal("unrelated state directory was blocked", err)
			}
			releaseWriter()
			select {
			case <-finished:
			case <-time.After(30 * time.Second):
				t.Fatal("writer did not settle")
			}
			if writeErr != nil {
				t.Fatal(writeErr)
			}
			values, revisions, err := reader.ListGrantsWithRevisions()
			if err != nil || len(values) != 1 || len(revisions) != 1 || revisions[doc.value.GrantID] != 0 || values[0].Status != doc.value.Status {
				t.Fatal("incorrect content/revision result", err)
			}
		})
	}
}

func TestGrantSnapshotInitialPrepareIsNotSuccessfulEmpty(t *testing.T) {
	store, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	entered, release, finished := make(chan struct{}), make(chan struct{}), make(chan struct{})
	var once sync.Once
	releaseWriter := func() { once.Do(func() { close(release) }) }
	restore := SetCommitBoundaryHook(func(phase string) {
		if phase == "prepared" {
			close(entered)
			<-release
		}
	})
	var writeErr error
	go func() {
		defer close(finished)
		_, writeErr = store.CommitGrant(GrantCommit{Grant: grant.Grant{GrantID: "initial", Status: "pending_approval"}, ExpectedRevision: -1})
	}()
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
		t.Fatal("writer did not reach prepare", writeErr)
	case <-time.After(30 * time.Second):
		t.Fatal("writer did not start")
	}
	if values, revisions, err := store.ListGrantsWithRevisions(); !errors.Is(err, ErrGrantsBusy) || values != nil || revisions != nil {
		t.Fatal("initial prepare appeared as successful empty list", err)
	}
	releaseWriter()
	select {
	case <-finished:
	case <-time.After(30 * time.Second):
		t.Fatal("writer did not finish")
	}
	if writeErr != nil {
		t.Fatal(writeErr)
	}
	values, revisions, err := store.ListGrantsWithRevisions()
	if err != nil || len(values) != 1 || values[0].GrantID != "initial" || revisions["initial"] != 0 {
		t.Fatal("initial committed snapshot missing", err)
	}
}
