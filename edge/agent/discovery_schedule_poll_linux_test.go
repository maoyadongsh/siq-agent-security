//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestSchedulePollRejectsOrphanAcknowledgement(t *testing.T) {
	for _, partial := range []bool{false, true} {
		t.Run(map[bool]string{false: "complete", true: "partial"}[partial], func(t *testing.T) {
			state, raw, now := scheduleJournalFixture(t)
			journal, err := prepareScheduleJournal(state, raw, 0, true, now)
			if err != nil {
				t.Fatal(err)
			}
			result := &DiscoveryScheduleState{Schema: "enterprise-discovery-schedule-state/v1",
				ScheduleID: journal.Request.ScheduleID, IntentDigest: journal.Request.IntentDigest,
				Status: "active", Revision: 1}
			if err := saveScheduleConfirmation(journal, result); err != nil {
				t.Fatal(err)
			}
			path, err := scheduleJournalPath()
			if err != nil {
				t.Fatal(err)
			}
			// Simulate incomplete recovery in this test's private state only.
			if err := os.Rename(path, path+".fixture-backup"); err != nil {
				t.Fatal(err)
			}
			ack := filepath.Join(filepath.Dir(path), "discovery-schedule-confirmed.json")
			if partial {
				if err := os.WriteFile(ack, []byte("partial"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			before, err := os.ReadFile(ack)
			if err != nil {
				t.Fatal(err)
			}
			beat := func(context.Context) error { t.Fatal("heartbeat invoked during validation"); return nil }
			if loop, err := scheduledHeartbeat(state, nil, beat); !errors.Is(err, errDiscoverySchedule) || loop != nil {
				t.Fatal("orphan acknowledgement treated as absence of schedule consent")
			}
			after, err := os.ReadFile(ack)
			if err != nil || !bytes.Equal(before, after) {
				t.Fatal("recovery material changed")
			}
			if _, err := os.Lstat(path); !errors.Is(err, os.ErrNotExist) {
				t.Fatal("missing journal recreated")
			}
		})
	}
}

func TestSchedulePollRequiresPrivateAcknowledgement(t *testing.T) {
	state, raw, now := scheduleJournalFixture(t)
	heartbeat := func(context.Context) error { return nil }
	if _, err := scheduledHeartbeat(state, nil, heartbeat); err != nil {
		t.Fatal(err)
	}
	journal, err := prepareScheduleJournal(state, raw, 0, true, now)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := scheduledHeartbeat(state, nil, heartbeat); err == nil {
		t.Fatal("pending consent accepted without acknowledgement")
	}
	result := &DiscoveryScheduleState{Schema: "enterprise-discovery-schedule-state/v1", ScheduleID: journal.Request.ScheduleID,
		IntentDigest: journal.Request.IntentDigest, Status: "active", Revision: 1}
	if err := saveScheduleConfirmation(journal, result); err != nil {
		t.Fatal(err)
	}
	if _, err := scheduledHeartbeat(state, nil, heartbeat); err != nil {
		t.Fatal(err)
	}
	state.EnvironmentID = "wrong-environment"
	if _, err := scheduledHeartbeat(state, nil, heartbeat); err == nil {
		t.Fatal("changed local binding accepted")
	}
}

func TestSchedulePollWindowBackoffAndStop(t *testing.T) {
	_, schedule, stamp := scheduleFixture(t)
	calls, beats := 0, 0
	failed, active := true, true
	loop := scheduleHeartbeatLoop(schedule, func(context.Context) error { beats++; return nil }, func(context.Context) (bool, error) {
		calls++
		if failed {
			return false, errors.New("synthetic failure")
		}
		return active, nil
	}, func() time.Time { return stamp })
	ctx := context.Background()
	loop(ctx)
	loop(ctx)
	if calls != 1 || beats != 2 {
		t.Fatal("retry suppression damaged heartbeat")
	}
	stamp = stamp.Add(30 * time.Second)
	failed = false
	loop(ctx)
	if calls != 2 {
		t.Fatal("retry missing")
	}
	stamp = stamp.Add(30 * time.Second)
	active = false
	loop(ctx)
	stamp = stamp.Add(time.Hour)
	loop(ctx)
	if calls != 3 {
		t.Fatal("inactive plan continued polling")
	}
	loop = scheduleHeartbeatLoop(schedule, func(context.Context) error { return nil }, func(context.Context) (bool, error) {
		t.Fatal("out of window request")
		return true, nil
	}, func() time.Time { return stamp })
	stamp, _ = time.Parse(time.RFC3339Nano, schedule.StartsAt)
	stamp = stamp.Add(-time.Second)
	loop(ctx)
	stamp, _ = time.Parse(time.RFC3339Nano, schedule.ExpiresAt)
	loop(ctx)
}

func TestSchedulePollTickCancellationPreemptsState(t *testing.T) {
	_, schedule, stamp := scheduleFixture(t)
	cases := []struct {
		name   string
		active bool
		err    error
	}{
		{"tick-error", true, errors.New("synthetic failure")},
		{"tick-active", true, nil},
		{"tick-inactive", false, nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			calls := 0
			var cancel context.CancelFunc
			loop := scheduleHeartbeatLoop(schedule, func(context.Context) error { return nil },
				func(ctx context.Context) (bool, error) {
					calls++
					if cancel != nil {
						cancel()
					}
					return tc.active, tc.err
				}, func() time.Time { return stamp })
			var ctx context.Context
			ctx, cancel = context.WithCancel(context.Background())
			defer cancel()
			if err := loop(ctx); !errors.Is(err, context.Canceled) {
				t.Fatalf("canceled tick returned %v", err)
			}
			if calls != 1 {
				t.Fatalf("calls=%d", calls)
			}
			cancel = nil
			if err := loop(context.Background()); err != nil {
				t.Fatalf("fresh context call failed: %v", err)
			}
			if calls != 2 {
				t.Fatal("cancellation left stopped or backoff side effects")
			}
		})
	}
}

func TestScheduleTickTransport(t *testing.T) {
	state, schedule, now := scheduleFixture(t)
	consent, err := prepareDiscoveryScheduleConfirmation(state, schedule, 0, true, now)
	if err != nil {
		t.Fatal(err)
	}
	for _, mode := range []string{"active", "revoked", "wrong-digest", "duplicate", "extra", "null", "bad-task", "redirect", "failure"} {
		t.Run(mode, func(t *testing.T) {
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if r.Method != "POST" || r.URL.Path != "/edge/v1/discovery-schedules/tick" || r.Header.Get("Authorization") != "Bearer synthetic-secret" {
					t.Error("request changed")
				}
				var body map[string]string
				if json.NewDecoder(r.Body).Decode(&body) != nil || len(body) != 3 || body["schedule_id"] != consent.ScheduleID || body["intent_digest"] != consent.IntentDigest || body["schema_version"] != "edge-discovery-schedule-tick/v1" {
					t.Error("scope/time override or malformed request")
				}
				if mode == "redirect" {
					w.Header().Set("Location", "/must-not-follow")
					w.WriteHeader(302)
					return
				}
				if mode == "failure" {
					w.WriteHeader(503)
					return
				}
				out := map[string]any{"schema_version": "edge-discovery-schedule-tick-result/v1", "schedule_id": consent.ScheduleID,
					"intent_digest": consent.IntentDigest, "status": "active", "task_ids": []string{"tsk_one"}}
				switch mode {
				case "revoked":
					out["status"] = "revoked"
					out["task_ids"] = []string{}
				case "wrong-digest":
					out["intent_digest"] = strings.Repeat("f", 64)
				case "extra":
					out["extra"] = true
				case "null":
					out["task_ids"] = nil
				case "bad-task":
					out["task_ids"] = []string{"tsk_one", "tsk_one"}
				}
				raw, _ := json.Marshal(out)
				if mode == "duplicate" {
					raw = append([]byte(`{"status":"active",`), raw[1:]...)
				}
				w.Write(raw)
			}))
			defer server.Close()
			body := consent
			body.Origin = server.URL
			client := NewClient(ClientConfig{ControlPlaneURL: server.URL, DeviceIdentity: body.Identity, Secret: "synthetic-secret"})
			active, err := client.tickDiscoverySchedule(context.Background(), body)
			valid := mode == "active" || mode == "revoked"
			if (err == nil) != valid || active != (mode == "active") || calls != 1 {
				t.Fatalf("mode=%s active=%v err=%v calls=%d", mode, active, err, calls)
			}
		})
	}
}
