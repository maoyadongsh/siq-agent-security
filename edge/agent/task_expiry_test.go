package main

import (
	"strings"
	"testing"
	"time"
)

func TestTaskExpiryRequiresDeadline(t *testing.T) {
	now := time.Date(2026, 9, 6, 12, 0, 0, 0, time.UTC)
	missing := &Task{ExpiresAt: ""}
	if !missing.Expired(now) {
		t.Fatal("empty expires_at must be expired (no unlimited validity)")
	}
	if err := missing.ExpiryError(now); err == nil || !strings.Contains(err.Error(), "expires_at missing") {
		t.Fatalf("want missing deadline error, got %v", err)
	}
	ws := &Task{ExpiresAt: "   "}
	if !ws.Expired(now) {
		t.Fatal("whitespace expires_at must be expired")
	}
}

func TestTaskExpiryUnparseableFailClosed(t *testing.T) {
	now := time.Date(2026, 9, 6, 12, 0, 0, 0, time.UTC)
	bad := &Task{ExpiresAt: "not-a-time"}
	if !bad.Expired(now) {
		t.Fatal("unparseable expires_at must be expired")
	}
	if err := bad.ExpiryError(now); err == nil || !strings.Contains(err.Error(), "unparseable") {
		t.Fatalf("want unparseable error, got %v", err)
	}
}

func TestTaskExpiryLeeway(t *testing.T) {
	exp := time.Date(2026, 9, 6, 12, 0, 0, 0, time.UTC)
	task := &Task{ExpiresAt: exp.Format(time.RFC3339)}

	if task.Expired(exp) {
		t.Fatal("exactly at expires_at must still be valid")
	}
	if task.Expired(exp.Add(TaskExpiryLeeway)) {
		t.Fatal("at expires_at+leeway boundary must still be valid (After, not Equal)")
	}
	if !task.Expired(exp.Add(TaskExpiryLeeway + time.Second)) {
		t.Fatal("past expires_at+leeway must be expired")
	}
	if task.Expired(exp.Add(-time.Hour)) {
		t.Fatal("before deadline must be valid")
	}
}

func TestTaskExpiryNaiveUTC(t *testing.T) {
	now := time.Date(2026, 9, 6, 12, 0, 0, 0, time.UTC)
	task := &Task{ExpiresAt: "2026-09-06T11:00:00.123456"} // naive → UTC
	if !task.Expired(now) {
		t.Fatal("naive UTC past deadline must expire")
	}
	future := &Task{ExpiresAt: "2026-09-06T13:00:00"}
	if future.Expired(now) {
		t.Fatal("naive UTC future deadline must be valid")
	}
}
