//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestScheduleRetirementPreparationPreservesHistoryAndBlocksUse(t *testing.T) {
	for _, mode := range []string{"confirmed", "unacknowledged", "active", "wrong-consent", "partial-receipt", "canceled"} {
		t.Run(mode, func(t *testing.T) {
			state, raw, now := scheduleJournalFixture(t)
			unlock, err := acquireTaskLock()
			if err != nil {
				t.Fatal(err)
			}
			defer unlock()
			journal, err := prepareScheduleJournal(state, raw, 0, true, now)
			if err != nil {
				t.Fatal(err)
			}
			result := &DiscoveryScheduleState{Schema: "enterprise-discovery-schedule-state/v1", ScheduleID: journal.Request.ScheduleID,
				IntentDigest: journal.Request.IntentDigest, Status: "active", Revision: 1}
			path, _ := scheduleJournalPath()
			dir := filepath.Dir(path)
			ackPath := filepath.Join(dir, "discovery-schedule-confirmed.json")
			if mode != "unacknowledged" {
				if err := saveScheduleConfirmation(journal, result); err != nil {
					t.Fatal(err)
				}
			}
			if mode == "partial-receipt" {
				if err := os.WriteFile(ackPath, []byte("partial"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			original, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			ack, ackErr := os.ReadFile(ackPath)
			if mode != "unacknowledged" && ackErr != nil {
				t.Fatal(ackErr)
			}
			client := newAuthedClient(state)
			calls := 0
			client.http.Transport = scheduleReadTransport(func(r *http.Request) (*http.Response, error) {
				calls++
				if r.Method != "GET" {
					t.Fatal("retirement mutated server")
				}
				status := "revoked"
				if mode == "active" {
					status = "active"
				}
				body, _ := json.Marshal(discoveryScheduleSnapshot{Schema: "edge-discovery-schedule-intent/v1",
					Intent: raw, Digest: journal.Request.IntentDigest, Status: status, Revision: 2})
				return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(body)), Header: make(http.Header)}, nil
			})
			consent := journal.Request.IntentDigest
			if mode == "wrong-consent" {
				consent = strings.Repeat("f", 64)
			}
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if mode == "canceled" {
				cancel()
			}
			digest, err := prepareScheduleRetirement(ctx, state, client, consent)
			valid := mode == "confirmed" || mode == "unacknowledged"
			if (err == nil) != valid {
				t.Fatalf("mode=%s err=%v", mode, err)
			}
			current, readErr := os.ReadFile(path)
			currentAck, currentAckErr := os.ReadFile(ackPath)
			if readErr != nil || !bytes.Equal(original, current) || !bytes.Equal(ack, currentAck) || (ackErr == nil) != (currentAckErr == nil) {
				t.Fatal("original recovery material changed")
			}
			markerPath := filepath.Join(dir, scheduleRetirementPendingName)
			if !valid {
				files, err := filepath.Glob(filepath.Join(dir, "discovery-schedule-history-*.json"))
				if err != nil || len(files) != 0 {
					t.Fatal("rejected preparation wrote history")
				}
				if _, err := os.Lstat(markerPath); !os.IsNotExist(err) {
					t.Fatal("rejected preparation published marker")
				}
				return
			}
			archivePath := filepath.Join(dir, "discovery-schedule-history-"+digest+".json")
			stored, err := readDeviceState(archivePath)
			if err != nil || bytes.Contains(stored, []byte(state.Secret)) || bytes.Contains(stored, []byte(state.SignerSeed)) {
				t.Fatal("archive unsafe")
			}
			var record scheduleRetirementArchive
			if json.Unmarshal(stored, &record) != nil || !bytes.Equal(record.Journal, original) || !bytes.Equal(record.Receipt, ack) || record.Revoked.Status != "revoked" {
				t.Fatal("archive does not preserve original bytes and revocation")
			}
			if _, err := readDeviceState(markerPath); err != nil || requireNoScheduleRetirement() == nil || calls != 1 {
				t.Fatal("missing private recovery marker or repeated read")
			}
			// A crash after moving originals must not enable ordinary startup/consent.
			if err := os.Rename(path, path+".fixture-backup"); err != nil {
				t.Fatal(err)
			}
			if mode == "confirmed" {
				if err := os.Rename(ackPath, ackPath+".fixture-backup"); err != nil {
					t.Fatal(err)
				}
			}
			if loop, err := scheduledHeartbeat(state, nil, func(context.Context) error { return nil }); err == nil || loop != nil {
				t.Fatal("unfinished retirement permitted startup")
			}
			if _, err := prepareScheduleJournal(state, raw, 0, true, now); err == nil {
				t.Fatal("unfinished retirement permitted new confirmation")
			}
		})
	}
}

func TestScheduleRetirementFinishAndInterruptedRecovery(t *testing.T) {
	for _, mode := range []string{"normal", "ack-moved", "both-moved", "wrong-consent", "no-longer-revoked", "archive-changed", "original-changed", "partial-marker"} {
		t.Run(mode, func(t *testing.T) {
			state, raw, now := scheduleJournalFixture(t)
			unlock, err := acquireTaskLock()
			if err != nil {
				t.Fatal(err)
			}
			defer unlock()
			journal, err := prepareScheduleJournal(state, raw, 0, true, now)
			if err != nil {
				t.Fatal(err)
			}
			if err := saveScheduleConfirmation(journal, &DiscoveryScheduleState{
				Schema: "enterprise-discovery-schedule-state/v1", ScheduleID: journal.Request.ScheduleID,
				IntentDigest: journal.Request.IntentDigest, Status: "active", Revision: 1}); err != nil {
				t.Fatal(err)
			}
			client := newAuthedClient(state)
			status := "revoked"
			calls := 0
			client.http.Transport = scheduleReadTransport(func(r *http.Request) (*http.Response, error) {
				calls++
				if r.Method != "GET" {
					t.Fatal("recovery attempted remote write")
				}
				body, _ := json.Marshal(discoveryScheduleSnapshot{Schema: "edge-discovery-schedule-intent/v1",
					Intent: raw, Digest: journal.Request.IntentDigest, Status: status, Revision: 2})
				return &http.Response{StatusCode: 200, Body: io.NopCloser(bytes.NewReader(body)), Header: make(http.Header)}, nil
			})
			digest, err := prepareScheduleRetirement(context.Background(), state, client, journal.Request.IntentDigest)
			if err != nil {
				t.Fatal(err)
			}
			path, _ := scheduleJournalPath()
			dir := filepath.Dir(path)
			ack := filepath.Join(dir, "discovery-schedule-confirmed.json")
			archive := filepath.Join(dir, "discovery-schedule-history-"+digest+".json")
			marker := filepath.Join(dir, scheduleRetirementPendingName)
			originalArchive, err := os.ReadFile(archive)
			if err != nil {
				t.Fatal(err)
			}
			consent := journal.Request.IntentDigest
			switch mode {
			case "ack-moved", "both-moved":
				if err := os.Rename(ack, ack+".fixture-backup"); err != nil {
					t.Fatal(err)
				}
				if mode == "both-moved" {
					if err := os.Rename(path, path+".fixture-backup"); err != nil {
						t.Fatal(err)
					}
				}
			case "wrong-consent":
				consent = strings.Repeat("f", 64)
			case "no-longer-revoked":
				status = "active"
			case "archive-changed":
				if err := os.WriteFile(archive, append(originalArchive, ' '), 0600); err != nil {
					t.Fatal(err)
				}
			case "original-changed":
				if err := os.WriteFile(path, []byte(`{"unexpected":true}`), 0600); err != nil {
					t.Fatal(err)
				}
			case "partial-marker":
				if err := os.WriteFile(marker, []byte(`{"schema_version":`), 0600); err != nil {
					t.Fatal(err)
				}
			}
			before, _ := os.ReadFile(path)
			beforeAck, _ := os.ReadFile(ack)
			err = finishScheduleRetirement(context.Background(), state, client, consent)
			valid := mode == "normal" || mode == "ack-moved" || mode == "both-moved"
			if (err == nil) != valid {
				t.Fatalf("mode=%s err=%v", mode, err)
			}
			if !valid {
				after, _ := os.ReadFile(path)
				afterAck, _ := os.ReadFile(ack)
				if !bytes.Equal(before, after) || !bytes.Equal(beforeAck, afterAck) || requireNoScheduleRetirement() == nil {
					t.Fatal("rejected recovery modified originals or unblocked startup")
				}
				return
			}
			for _, absent := range []string{path, ack, marker} {
				if _, err := os.Lstat(absent); !os.IsNotExist(err) {
					t.Fatal("retired original or marker still present")
				}
			}
			afterArchive, err := os.ReadFile(archive)
			if err != nil || !bytes.Equal(originalArchive, afterArchive) || calls != 2 {
				t.Fatal("history changed or online verification missing")
			}
			if _, err := readDeviceState(filepath.Join(dir, "discovery-schedule-retired-"+digest+".json")); err != nil {
				t.Fatal("durable completion missing")
			}
			if err := requireNoScheduleRetirement(); err != nil {
				t.Fatal("completed retirement still blocked")
			}
			if _, err := prepareScheduleJournal(state, raw, 0, false, now); err == nil {
				t.Fatal("retirement granted new consent")
			}
		})
	}
}

func TestScheduleRetirementReusesOnlyIdenticalUnmarkedHistory(t *testing.T) {
	state, _, _ := scheduleJournalFixture(t)
	_ = state
	dir, err := scheduleStateDirectory()
	if err != nil {
		t.Fatal(err)
	}
	defer dir.Close()
	const name = "discovery-schedule-history-fixture.json"
	raw := []byte(`{"synthetic":true}`)
	if writeScheduleRetirementFile(dir, name, raw) != nil || writeScheduleRetirementFile(dir, name, raw) != nil {
		t.Fatal("identical durable copy not reusable")
	}
	if writeScheduleRetirementFile(dir, name, []byte(`{"synthetic":false}`)) == nil {
		t.Fatal("existing history overwritten")
	}
	stored, err := readScheduleRetirementFile(dir, name)
	if err != nil || !bytes.Equal(stored, raw) {
		t.Fatal("history bytes changed")
	}
}
