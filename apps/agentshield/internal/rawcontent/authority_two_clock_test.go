package rawcontent

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// Taskbook B04 (§9): 授权期限和保留期限不能混淆 — a grant whose authorization
// duration has elapsed must stop NEW captures while the already-captured
// ciphertext stays readable until its own retention-derived expiry, and the
// later purge deletes only the ciphertext, never the grant/audit facts.
func TestGrantExpiryStopsNewCaptureButCiphertextSurvivesUntilRetention(t *testing.T) {
	dir, store, authority, _ := testAuthority(t, 6*time.Hour)
	base := time.Date(2026, 9, 15, 12, 0, 0, 0, time.UTC)
	// Authorization duration 30 minutes; retention 2 hours. The two clocks differ.
	grant, err := authority.Issue("PRIVATE_TASK", []string{"input"}, "PRIVATE_ACTOR", 30*time.Minute, 2*time.Hour, 512, base)
	if err != nil {
		t.Fatal(err)
	}
	prepared, err := Prepare("input", []Field{{Path: "/prompt", Value: "captured before grant expiry"}})
	if err != nil {
		t.Fatal(err)
	}
	envelope, err := authority.Capture(grant.GrantID, "PRIVATE_TASK", prepared, base.Add(time.Minute))
	if err != nil || envelope.ExpiresAt != "2026-09-15T14:01:00Z" {
		t.Fatal("envelope expiry must derive from capture time + retention, not grant expiry", envelope, err)
	}

	// After the authorization period ends: no new captures…
	expiredNow := base.Add(31 * time.Minute)
	if _, err := authority.Capture(grant.GrantID, "PRIVATE_TASK", prepared, expiredNow); !errors.Is(err, ErrExpired) {
		t.Fatal("capture after grant expiry accepted", err)
	}
	if _, err := authority.Get(grant.GrantID, expiredNow); !errors.Is(err, ErrExpired) {
		t.Fatal("expired grant resolved as active", err)
	}
	// …but the ciphertext remains readable inside its own retention window.
	fields, _, err := store.Read("PRIVATE_TASK", envelope.RecordID, expiredNow)
	if err != nil || len(fields) != 1 || fields[0].Value != "captured before grant expiry" {
		t.Fatal("ciphertext did not survive authorization expiry", fields, err)
	}

	// The envelope outlives the grant by construction: grant expired at 12:30,
	// ciphertext stays until 14:01. Once retention elapses, reads are refused…
	retentionNow := base.Add(2*time.Hour + time.Minute)
	if _, _, err := store.Read("PRIVATE_TASK", envelope.RecordID, retentionNow); !errors.Is(err, ErrExpired) {
		t.Fatal("read past retention accepted", err)
	}
	// …and purge deletes exactly the expired ciphertext, leaving grant facts.
	before, err := os.ReadDir(filepath.Join(dir, "raw-task-content-authority"))
	if err != nil {
		t.Fatal(err)
	}
	saved := map[string][]byte{}
	for _, entry := range before {
		raw, readErr := os.ReadFile(filepath.Join(dir, "raw-task-content-authority", entry.Name()))
		if readErr != nil {
			t.Fatal(readErr)
		}
		saved[entry.Name()] = raw
	}
	result, err := store.PurgeExpired(retentionNow)
	if err != nil || result.Deleted != 1 || result.Bytes <= 0 {
		t.Fatal("purge scope", result, err)
	}
	if _, err := os.Stat(filepath.Join(dir, "raw-task-content", envelope.RecordID+".json")); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("expired ciphertext not purged", err)
	}
	after, err := os.ReadDir(filepath.Join(dir, "raw-task-content-authority"))
	if err != nil {
		t.Fatal(err)
	}
	if len(before) != len(after) || len(after) == 0 {
		t.Fatal("purge touched grant facts", len(before), len(after))
	}
	for i := range before {
		raw, readErr := os.ReadFile(filepath.Join(dir, "raw-task-content-authority", after[i].Name()))
		if readErr != nil || !bytes.Equal(raw, saved[after[i].Name()]) {
			t.Fatal("purge altered authority bytes", readErr)
		}
		if before[i].Name() != after[i].Name() {
			t.Fatal("grant file changed by purge", before[i].Name(), after[i].Name())
		}
	}
}
