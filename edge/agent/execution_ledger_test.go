package main

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func sampleTask(id, connector string) *Task {
	payload, _ := json.Marshal(map[string]any{"connector": connector})
	return &Task{
		TaskID:        id,
		TaskType:      "scan",
		EnvironmentID: "env-1",
		Payload:       payload,
		ExpiresAt:     time.Now().UTC().Add(time.Hour).Format(time.RFC3339),
	}
}

func TestTaskContentDigestStableAndSensitive(t *testing.T) {
	a := sampleTask("tsk-1", "hermes")
	b := sampleTask("tsk-1", "hermes")
	da, err := TaskContentDigest(a)
	if err != nil {
		t.Fatal(err)
	}
	db, err := TaskContentDigest(b)
	if err != nil {
		t.Fatal(err)
	}
	if da != db || len(da) != 64 {
		t.Fatalf("digest unstable: %q vs %q", da, db)
	}
	b.Payload, _ = json.Marshal(map[string]any{"connector": "openclaw"})
	db2, err := TaskContentDigest(b)
	if err != nil {
		t.Fatal(err)
	}
	if da == db2 {
		t.Fatal("payload change must change content digest")
	}
}

func TestExecLedgerReuseAndConflict(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)

	t1 := sampleTask("tsk-reuse", "hermes")
	rcpt := &Receipt{
		TaskID:         t1.TaskID,
		DeviceIdentity: "edge-1",
		Status:         "success",
		CandidateCount: 1,
		EvidenceCount:  1,
		EvidenceIDs:    []string{"ev:1"},
		CompletedAt:    "2026-09-06T00:00:00Z",
	}
	if err := SaveExecLedgerRecord(t1, rcpt); err != nil {
		t.Fatal(err)
	}
	got, err := LookupExecReuse(t1)
	if err != nil || got == nil {
		t.Fatalf("reuse: %v %#v", err, got)
	}
	if got.Status != "success" || got.CandidateCount != 1 {
		t.Fatalf("unexpected reused receipt: %+v", got)
	}

	mutated := sampleTask("tsk-reuse", "openclaw")
	_, err = LookupExecReuse(mutated)
	if err == nil || !strings.Contains(err.Error(), "task_content_conflict") {
		t.Fatalf("expected content conflict, got %v", err)
	}
}

func TestExecLedgerSkipsExpiryFailures(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)

	t1 := sampleTask("tsk-exp", "hermes")
	rcpt := &Receipt{TaskID: t1.TaskID, Status: "failed", ErrorCode: "expired"}
	if err := SaveExecLedgerRecord(t1, rcpt); err != nil {
		t.Fatal(err)
	}
	got, err := LookupExecReuse(t1)
	if err != nil || got != nil {
		t.Fatalf("expiry must not be journaled for reuse: %#v err=%v", got, err)
	}
}

func TestExecLedgerRejectsUnsafeTaskID(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	t1 := sampleTask("../escape", "hermes")
	if err := SaveExecLedgerRecord(t1, &Receipt{TaskID: t1.TaskID, Status: "success"}); err == nil {
		t.Fatal("path traversal task_id must be rejected")
	}
}
