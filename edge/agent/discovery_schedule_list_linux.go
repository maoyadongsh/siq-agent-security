//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"time"
)

// Read-only discovery of this device's own pending_confirmation schedules
// (GET /edge/v1/discovery-schedules). The endpoint enumerates rows that are
// waiting for *this* device's separate Ed25519 confirmation; listing one is not
// authorization, and nothing in this file selects, signs, journals, ticks or
// activates a plan. Every request is a GET and the result stays in memory.
//
// Bounds are explicit: the endpoint is not a general plan overview, and a large
// organization-side backlog must fail loudly instead of paging forever.
const (
	pendingListPageLimit = 100    // the server's own maximum
	pendingListMaxPages  = 8      // bounded paging
	pendingListMaxItems  = 200    // bounded candidate count
	pendingListPageBytes = 262144 // one page's response budget
)

var (
	errPendingScheduleIntegrity = fmt.Errorf("%w; pending_schedule_integrity_failed; do not select or confirm any listed plan; report the schedule IDs to the organization console", errDiscoverySchedule)
	errPendingScheduleTooMany   = fmt.Errorf("%w; pending_schedule_result_too_large; organize plans in the organization console or re-run with an explicit --schedule-id", errDiscoverySchedule)
	pendingScheduleIDPattern    = regexp.MustCompile(`^eds-[a-f0-9]{32}$`)
)

type pendingScheduleCandidate struct {
	ID        string
	Digest    string
	Status    string
	Revision  int64
	StartsAt  string
	ExpiresAt string
	Intent    []byte
}

// Candidates are never treated as a complete list when err is non-nil. On an
// integrity failure the caller may report only IntegrityFailed, which holds
// controlled schedule IDs and nothing else.
type pendingScheduleDiscovery struct {
	EvaluatedAt     string
	Candidates      []pendingScheduleCandidate
	IntegrityFailed []string
}

type pendingSchedulePage struct {
	EvaluatedAt     string
	Candidates      []pendingScheduleCandidate
	IntegrityFailed []string
	NextCursor      string
}

// Exact wire field set. encoding/json's struct decoder accepts case-insensitive
// aliases and ignores unknown fields, so the object is validated before any
// value from it is decoded. `nullable` names the only field the frozen contract
// allows to be null (next_cursor on the last page).
func pendingScheduleFields(raw []byte, allowed []string, nullable string) (map[string]json.RawMessage, bool) {
	var object map[string]json.RawMessage
	if json.Unmarshal(raw, &object) != nil || object == nil || len(object) != len(allowed) {
		return nil, false
	}
	keys := make(map[string]bool, len(allowed))
	for _, key := range allowed {
		keys[key] = true
	}
	for key, value := range object {
		if !keys[key] || (string(value) == "null" && key != nullable) {
			return nil, false
		}
	}
	return object, true
}

func parsePendingScheduleCandidate(raw []byte, identity string) (pendingScheduleCandidate, error) {
	var candidate pendingScheduleCandidate
	if _, ok := pendingScheduleFields(raw, []string{"schedule_id", "status", "revision", "intent", "intent_digest"}, ""); !ok {
		return candidate, errDiscoverySchedule
	}
	var wire struct {
		ScheduleID   string          `json:"schedule_id"`
		Status       string          `json:"status"`
		Revision     int64           `json:"revision"`
		Intent       json.RawMessage `json:"intent"`
		IntentDigest string          `json:"intent_digest"`
	}
	// The endpoint only ever enumerates pending_confirmation rows; any other
	// status means this is not the frozen contract, so fail closed rather than
	// presenting an unconfirmed or revoked plan as a pending task.
	if json.Unmarshal(raw, &wire) != nil || !pendingScheduleIDPattern.MatchString(wire.ScheduleID) ||
		wire.Status != "pending_confirmation" || wire.Revision != 0 {
		return candidate, errDiscoverySchedule
	}
	// Reuse the same strict intent parser, digest and device-identity binding as
	// the named read path: no second, looser parser for list items.
	intent, err := parseDiscoverySchedule(wire.Intent)
	if err != nil || intent.ID != wire.ScheduleID || intent.Identity != identity {
		return candidate, errDiscoverySchedule
	}
	digest, err := intent.digest()
	if err != nil || digest != wire.IntentDigest {
		return candidate, errDiscoverySchedule
	}
	return pendingScheduleCandidate{ID: wire.ScheduleID, Digest: digest, Status: wire.Status,
		Revision: wire.Revision, StartsAt: intent.StartsAt, ExpiresAt: intent.ExpiresAt,
		Intent: append([]byte(nil), wire.Intent...)}, nil
}

func parsePendingSchedulePage(raw []byte, cursor, identity string) (*pendingSchedulePage, error) {
	if _, ok := pendingScheduleFields(raw, []string{"schema_version", "evaluated_at", "items", "integrity_failed", "next_cursor"}, "next_cursor"); !ok {
		return nil, errDiscoverySchedule
	}
	// encoding/json keeps the last of duplicate keys; reject duplicates first.
	if checkStateJSON(json.NewDecoder(bytes.NewReader(raw)), 0) != nil {
		return nil, errDiscoverySchedule
	}
	var wire struct {
		SchemaVersion   string            `json:"schema_version"`
		EvaluatedAt     string            `json:"evaluated_at"`
		Items           []json.RawMessage `json:"items"`
		IntegrityFailed []json.RawMessage `json:"integrity_failed"`
		NextCursor      *string           `json:"next_cursor"`
	}
	if json.Unmarshal(raw, &wire) != nil || wire.SchemaVersion != "enterprise-discovery-schedule-pending-list/v1" {
		return nil, errDiscoverySchedule
	}
	if !scheduleTimestamp.MatchString(wire.EvaluatedAt) {
		return nil, errDiscoverySchedule
	}
	if _, err := time.Parse(time.RFC3339Nano, wire.EvaluatedAt); err != nil {
		return nil, errDiscoverySchedule
	}
	page := &pendingSchedulePage{EvaluatedAt: wire.EvaluatedAt}
	if len(wire.Items)+len(wire.IntegrityFailed) > pendingListPageLimit {
		return nil, errPendingScheduleTooMany
	}
	previousIntegrityID := cursor
	for _, entry := range wire.IntegrityFailed {
		var id string
		// An entry that is not a plain schedule ID is itself untrusted content.
		if json.Unmarshal(entry, &id) != nil || !pendingScheduleIDPattern.MatchString(id) || id <= previousIntegrityID {
			return nil, errDiscoverySchedule
		}
		page.IntegrityFailed = append(page.IntegrityFailed, id)
		previousIntegrityID = id
	}
	previousID := cursor
	for _, entry := range wire.Items {
		candidate, err := parsePendingScheduleCandidate(entry, identity)
		if err != nil {
			return nil, err
		}
		// The server contract orders rows by schedule ID and applies a strict
		// `id > cursor` predicate. Enforce both here: otherwise a malformed page
		// could skip other pending plans and make one observed item look unique.
		if candidate.ID <= previousID {
			return nil, errDiscoverySchedule
		}
		page.Candidates = append(page.Candidates, candidate)
		previousID = candidate.ID
	}
	if wire.NextCursor != nil {
		// A cursor that does not strictly advance can never make progress; a
		// repeat, rewind, empty advancing page, or cursor that is not the last
		// projected row is a contract violation. Without this binding, a server
		// bug could hide additional candidates behind a fabricated cursor.
		lastID := previousID
		if previousIntegrityID > lastID {
			lastID = previousIntegrityID
		}
		if !pendingScheduleIDPattern.MatchString(*wire.NextCursor) ||
			len(page.Candidates)+len(page.IntegrityFailed) == 0 || *wire.NextCursor != lastID {
			return nil, errDiscoverySchedule
		}
		page.NextCursor = *wire.NextCursor
	}
	if len(page.IntegrityFailed) > 0 {
		return page, errPendingScheduleIntegrity
	}
	return page, nil
}

// One read-only page. No selection, signing, confirmation journal or receipt.
// The caller may already hold the existing local task-lock coordination file.
func (c *Client) readPendingSchedulePage(ctx context.Context, cursor string) (*pendingSchedulePage, error) {
	if ctx.Err() != nil || c.configErr != nil || c.identity == "" || c.secret == "" ||
		(cursor != "" && !pendingScheduleIDPattern.MatchString(cursor)) {
		return nil, errDiscoverySchedule
	}
	target := c.base + "/edge/v1/discovery-schedules?limit=" + strconv.Itoa(pendingListPageLimit)
	if cursor != "" {
		target += "&cursor=" + url.QueryEscape(cursor)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		return nil, errDiscoverySchedule
	}
	req.Header.Set("Authorization", "Bearer "+c.secret)
	req.Header.Set("X-Edge-Identity", c.identity)
	req.Header.Set("X-Edge-Version", c.version)
	transport := *c.http
	transport.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	response, err := transport.Do(req)
	if err != nil {
		return nil, errDiscoverySchedule
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, errDiscoverySchedule
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, pendingListPageBytes+1))
	if err != nil || len(raw) > pendingListPageBytes || ctx.Err() != nil {
		return nil, errDiscoverySchedule
	}
	return parsePendingSchedulePage(raw, cursor, c.identity)
}

// Bounded discovery. A partial result is returned alongside the error so the
// caller can name the affected schedule IDs, but it is never a complete list.
func (c *Client) discoverPendingSchedules(ctx context.Context) (*pendingScheduleDiscovery, error) {
	result := &pendingScheduleDiscovery{}
	if ctx.Err() != nil || c.configErr != nil || c.identity == "" || c.secret == "" {
		return result, errDiscoverySchedule
	}
	cursor := ""
	for page := 0; page < pendingListMaxPages; page++ {
		current, err := c.readPendingSchedulePage(ctx, cursor)
		if err != nil {
			// A partially loaded set is never a list: drop everything decoded so
			// far so no caller can mistake it for the device's pending work. Only
			// the controlled schedule IDs survive, for the failure report.
			if current != nil {
				result.IntegrityFailed = current.IntegrityFailed
			}
			result.Candidates = nil
			return result, err
		}
		if result.EvaluatedAt == "" {
			result.EvaluatedAt = current.EvaluatedAt
		}
		result.Candidates = append(result.Candidates, current.Candidates...)
		if len(result.Candidates) > pendingListMaxItems {
			result.Candidates = nil
			return result, errPendingScheduleTooMany
		}
		if current.NextCursor == "" {
			if ctx.Err() != nil {
				return result, errDiscoverySchedule
			}
			return result, nil
		}
		cursor = current.NextCursor
	}
	return result, errPendingScheduleTooMany
}
