//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

// Only the existing serve lock holder calls this. Pending consent alone cannot
// activate polling; an exact, private acknowledgement must also be present.
func scheduledHeartbeat(state *State, client *Client, heartbeat func(context.Context) error) (func(context.Context) error, error) {
	if requireNoScheduleRetirement() != nil {
		return nil, errDiscoverySchedule
	}
	path, err := scheduleJournalPath()
	if err != nil {
		return nil, errDiscoverySchedule
	}
	if _, err := os.Lstat(path); errors.Is(err, os.ErrNotExist) {
		// An acknowledgement without its signed request is incomplete recovery,
		// not an installation that never configured a schedule. Preserve it.
		ackPath := filepath.Join(filepath.Dir(path), "discovery-schedule-confirmed.json")
		if _, err := os.Lstat(ackPath); !errors.Is(err, os.ErrNotExist) {
			return nil, errDiscoverySchedule
		}
		return heartbeat, nil
	} else if err != nil {
		return nil, errDiscoverySchedule
	}
	journal, err := readScheduleJournal(state)
	if err != nil {
		return nil, errDiscoverySchedule
	}
	raw, err := readDeviceState(filepath.Join(filepath.Dir(path), "discovery-schedule-confirmed.json"))
	if err != nil || len(raw) > 8192 {
		return nil, errDiscoverySchedule
	}
	if !validScheduleAcknowledgement(raw, journal) {
		return nil, errDiscoverySchedule
	}
	schedule, err := parseDiscoverySchedule(journal.Intent)
	if err != nil {
		return nil, errDiscoverySchedule
	}
	return scheduleHeartbeatLoop(*schedule, heartbeat, func(ctx context.Context) (bool, error) {
		return client.tickDiscoverySchedule(ctx, journal.Request)
	}, time.Now), nil
}

// Tick failures back off independently; they do not suppress fresh heartbeats.
// The response's task IDs are never executed here: normal signed task claiming
// and receipts remain the only execution path.
func scheduleHeartbeatLoop(schedule DiscoverySchedule, heartbeat func(context.Context) error, tick func(context.Context) (bool, error), now func() time.Time) func(context.Context) error {
	start, _ := time.Parse(time.RFC3339Nano, schedule.StartsAt)
	end, _ := time.Parse(time.RFC3339Nano, schedule.ExpiresAt)
	var retryAt time.Time
	delay := 30 * time.Second
	stopped := false
	return func(ctx context.Context) error {
		if err := heartbeat(ctx); err != nil {
			return err
		}
		stamp := now()
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if stopped || stamp.Before(start) || !stamp.Before(end) || stamp.Before(retryAt) {
			return nil
		}
		active, err := tick(ctx)
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if err != nil {
			retryAt = stamp.Add(delay)
			delay = min(delay*2, 15*time.Minute)
			log.Print("edge discovery schedule unavailable; bounded retry scheduled")
			return nil
		}
		stopped = !active
		delay = 30 * time.Second
		retryAt = stamp.Add(delay)
		return nil
	}
}

func (c *Client) tickDiscoverySchedule(ctx context.Context, consent DiscoveryScheduleConfirmation) (bool, error) {
	if c.configErr != nil || !consent.valid() || consent.Identity != c.identity || consent.Origin != c.base || c.secret == "" {
		return false, errDiscoverySchedule
	}
	body, _ := json.Marshal(map[string]string{"schema_version": "edge-discovery-schedule-tick/v1",
		"schedule_id": consent.ScheduleID, "intent_digest": consent.IntentDigest})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+"/edge/v1/discovery-schedules/tick", bytes.NewReader(body))
	if err != nil {
		return false, errDiscoverySchedule
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.secret)
	req.Header.Set("X-Edge-Identity", c.identity)
	req.Header.Set("X-Edge-Version", c.version)
	transport := *c.http
	transport.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	response, err := transport.Do(req)
	if err != nil {
		return false, errDiscoverySchedule
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return false, errDiscoverySchedule
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, 8193))
	if err != nil || len(raw) > 8192 {
		return false, errDiscoverySchedule
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	if checkStateJSON(decoder, 0) != nil || decoder.Decode(new(any)) != io.EOF {
		return false, errDiscoverySchedule
	}
	if _, ok := rotationJSONFields(raw, []string{"schema_version", "schedule_id", "intent_digest", "status", "task_ids"}, true); !ok {
		return false, errDiscoverySchedule
	}
	var result struct {
		Schema string   `json:"schema_version"`
		ID     string   `json:"schedule_id"`
		Digest string   `json:"intent_digest"`
		Status string   `json:"status"`
		Tasks  []string `json:"task_ids"`
	}
	if json.Unmarshal(raw, &result) != nil || result.Schema != "edge-discovery-schedule-tick-result/v1" ||
		result.ID != consent.ScheduleID || result.Digest != consent.IntentDigest || result.Tasks == nil || len(result.Tasks) > 32 {
		return false, errDiscoverySchedule
	}
	switch result.Status {
	case "active", "pending_confirmation", "paused", "revoked":
	default:
		return false, errDiscoverySchedule
	}
	seen := map[string]bool{}
	for _, id := range result.Tasks {
		if !initialTaskID.MatchString(id) || seen[id] || result.Status != "active" {
			return false, errDiscoverySchedule
		}
		seen[id] = true
	}
	return result.Status == "active", nil
}
