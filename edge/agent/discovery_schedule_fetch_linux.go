//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"regexp"
)

type discoveryScheduleSnapshot struct {
	Schema   string          `json:"schema_version"`
	Intent   json.RawMessage `json:"intent"`
	Digest   string          `json:"intent_digest"`
	Status   string          `json:"status"`
	Revision int64           `json:"revision"`
}

// Initial confirmation still accepts only a never-confirmed intent.
func (c *Client) fetchDiscoverySchedule(ctx context.Context, id string) ([]byte, error) {
	result, err := c.readDiscoverySchedule(ctx, id)
	if err != nil || result.Status != "pending_confirmation" || result.Revision != 0 {
		return nil, errDiscoverySchedule
	}
	return result.Intent, nil
}

// Reads one named record only. No fallback selection, signing or local writes.
func (c *Client) readDiscoverySchedule(ctx context.Context, id string) (*discoveryScheduleSnapshot, error) {
	if ctx.Err() != nil || c.configErr != nil || c.identity == "" || c.secret == "" || !regexp.MustCompile(`^eds-[a-f0-9]{32}$`).MatchString(id) {
		return nil, errDiscoverySchedule
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.base+"/edge/v1/discovery-schedules/"+id, nil)
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
	raw, err := io.ReadAll(io.LimitReader(response.Body, 16385))
	if err != nil || len(raw) > 16384 || ctx.Err() != nil {
		return nil, errDiscoverySchedule
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	if checkStateJSON(d, 0) != nil || d.Decode(new(any)) != io.EOF {
		return nil, errDiscoverySchedule
	}
	if _, ok := rotationJSONFields(raw, []string{"schema_version", "intent", "intent_digest", "status", "revision"}, true); !ok {
		return nil, errDiscoverySchedule
	}
	var result discoveryScheduleSnapshot
	if json.Unmarshal(raw, &result) != nil || result.Schema != "edge-discovery-schedule-intent/v1" || result.Revision < 0 {
		return nil, errDiscoverySchedule
	}
	switch result.Status {
	case "pending_confirmation":
	case "active", "paused", "revoked":
		if result.Revision == 0 {
			return nil, errDiscoverySchedule
		}
	default:
		return nil, errDiscoverySchedule
	}
	intent, err := parseDiscoverySchedule(result.Intent)
	if err != nil || intent.ID != id || intent.Identity != c.identity {
		return nil, errDiscoverySchedule
	}
	digest, err := intent.digest()
	if err != nil || digest != result.Digest {
		return nil, errDiscoverySchedule
	}
	return &result, nil
}

// Retirement's read-only prerequisite; callers must still obtain explicit
// local consent and durably preserve the journal before changing local files.
func (c *Client) verifyRevokedSchedule(ctx context.Context, state *State, journal *discoveryScheduleJournal) (*DiscoveryScheduleState, error) {
	if journal == nil || journal.validate(state) != nil || c.identity != journal.Request.Identity || c.base != journal.Request.Origin {
		return nil, errDiscoverySchedule
	}
	result, err := c.readDiscoverySchedule(ctx, journal.Request.ScheduleID)
	if err != nil || result.Status != "revoked" || result.Digest != journal.Request.IntentDigest || result.Revision <= journal.Request.Revision {
		return nil, errDiscoverySchedule
	}
	original, err := parseDiscoverySchedule(journal.Intent)
	if err != nil {
		return nil, errDiscoverySchedule
	}
	observed, err := parseDiscoverySchedule(result.Intent)
	if err != nil || *observed != *original || ctx.Err() != nil {
		return nil, errDiscoverySchedule
	}
	return &DiscoveryScheduleState{Schema: "enterprise-discovery-schedule-state/v1",
		ScheduleID: journal.Request.ScheduleID, IntentDigest: result.Digest,
		Status: result.Status, Revision: result.Revision}, nil
}
