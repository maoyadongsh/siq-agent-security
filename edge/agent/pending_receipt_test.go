package main

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

type fakePoster struct {
	calls []string
	fail  map[string]error
}

func (f *fakePoster) PostReceipt(_ context.Context, taskID string, _ *Receipt) error {
	f.calls = append(f.calls, taskID)
	if f.fail != nil {
		if err, ok := f.fail[taskID]; ok {
			return err
		}
	}
	return nil
}

func TestPendingReceiptJournalRoundTrip(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)

	rcpt := &Receipt{
		TaskID:         "tsk-abc",
		DeviceIdentity: "edge-1",
		Status:         "success",
		CandidateCount: 2,
		EvidenceCount:  3,
		EvidenceIDs:    []string{"ev:1", "ev:2", "ev:3"},
		CompletedAt:    "2026-09-06T00:00:00Z",
	}
	if err := SavePendingReceipt(rcpt); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "pending_receipts", "tsk-abc.json")
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("journal file missing: %v", err)
	}
	got, err := LoadPendingReceipt("tsk-abc")
	if err != nil || got == nil {
		t.Fatalf("load: %v %#v", err, got)
	}
	if got.Status != "success" || got.CandidateCount != 2 || len(got.EvidenceIDs) != 3 {
		t.Fatalf("unexpected receipt: %+v", got)
	}
	if err := RemovePendingReceipt("tsk-abc"); err != nil {
		t.Fatal(err)
	}
	got, err = LoadPendingReceipt("tsk-abc")
	if err != nil || got != nil {
		t.Fatalf("after remove want nil, got %#v err=%v", got, err)
	}
}

func TestDrainPendingReceiptsPostsAndClears(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)

	for _, id := range []string{"tsk-1", "tsk-2"} {
		if err := SavePendingReceipt(&Receipt{TaskID: id, Status: "success", CompletedAt: "t"}); err != nil {
			t.Fatal(err)
		}
	}
	poster := &fakePoster{fail: map[string]error{"tsk-2": errors.New("network")}}
	n, err := DrainPendingReceipts(context.Background(), poster)
	if n != 1 {
		t.Fatalf("posted=%d want 1", n)
	}
	if err == nil {
		t.Fatal("expected error from failed post")
	}
	if len(poster.calls) != 2 {
		t.Fatalf("calls=%v", poster.calls)
	}
	// tsk-1 cleared; tsk-2 remains for retry
	ids, err := ListPendingReceiptTaskIDs()
	if err != nil {
		t.Fatal(err)
	}
	if len(ids) != 1 || ids[0] != "tsk-2" {
		t.Fatalf("remaining ids=%v", ids)
	}
}

func TestSavePendingReceiptRejectsUnsafeTaskID(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	if err := SavePendingReceipt(&Receipt{TaskID: "../escape", Status: "success"}); err == nil {
		t.Fatal("path traversal task_id must be rejected")
	}
}
