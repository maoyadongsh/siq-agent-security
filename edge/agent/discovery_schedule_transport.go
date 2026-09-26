package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"math"
	"net/http"
	"regexp"
	"time"
)

type DiscoveryScheduleState struct {
	Schema       string `json:"schema_version"`
	ScheduleID   string `json:"schedule_id"`
	Status       string `json:"status"`
	Revision     int64  `json:"revision"`
	IntentDigest string `json:"intent_digest"`
}

func (r DiscoveryScheduleConfirmation) valid() bool {
	identifier := regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`)
	digest := regexp.MustCompile(`^[a-f0-9]{64}$`)
	timestamp, err := time.Parse(time.RFC3339Nano, r.ConfirmedAt)
	return r.Schema == "edge-discovery-schedule-confirm/v1" &&
		regexp.MustCompile(`^eds-[a-f0-9]{32}$`).MatchString(r.ScheduleID) &&
		identifier.MatchString(r.Identity) && identifier.MatchString(r.Environment) &&
		digest.MatchString(r.IntentDigest) && digest.MatchString(r.PlanDigest) &&
		r.UserConfirmed && r.Revision >= 0 && r.Revision < math.MaxInt64 &&
		scheduleTimestamp.MatchString(r.ConfirmedAt) && err == nil && timestamp.Year() >= 1 &&
		regexp.MustCompile(`^[a-f0-9]{128}$`).MatchString(r.Signature)
}

func scheduleStateFields(raw []byte) bool {
	fields := map[string]bool{"schema_version": true, "schedule_id": true, "status": true, "revision": true, "intent_digest": true}
	d := json.NewDecoder(bytes.NewReader(raw))
	start, err := d.Token()
	if err != nil || start != json.Delim('{') {
		return false
	}
	for d.More() {
		key, err := d.Token()
		name, ok := key.(string)
		if err != nil || !ok || !fields[name] {
			return false
		}
		delete(fields, name)
		var value json.RawMessage
		if d.Decode(&value) != nil || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return false
		}
	}
	end, err := d.Token()
	return err == nil && end == json.Delim('}') && len(fields) == 0 && d.Decode(new(any)) == io.EOF
}

// One explicit attempt only. Caller must persist consent and exact signed request
// first. Errors reveal no upstream body and never mutate credentials or state.
func (c *Client) ConfirmDiscoverySchedule(ctx context.Context, body DiscoveryScheduleConfirmation) (*DiscoveryScheduleState, error) {
	if c.configErr != nil || !body.valid() || body.Identity != c.identity || body.Origin != c.base || c.secret == "" {
		return nil, errDiscoverySchedule
	}
	raw, err := json.Marshal(body)
	if err != nil {
		return nil, errDiscoverySchedule
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.base+"/edge/v1/discovery-schedules/confirm", bytes.NewReader(raw))
	if err != nil {
		return nil, errDiscoverySchedule
	}
	req.Header.Set("Content-Type", "application/json")
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
	data, err := io.ReadAll(io.LimitReader(response.Body, 4097))
	if err != nil || len(data) > 4096 || !scheduleStateFields(data) {
		return nil, errDiscoverySchedule
	}
	var result DiscoveryScheduleState
	if json.Unmarshal(data, &result) != nil || result.Schema != "enterprise-discovery-schedule-state/v1" ||
		result.ScheduleID != body.ScheduleID || result.IntentDigest != body.IntentDigest || result.Status != "active" ||
		result.Revision <= body.Revision {
		return nil, errDiscoverySchedule
	}
	return &result, nil
}
