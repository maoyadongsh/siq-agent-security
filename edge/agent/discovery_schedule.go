package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"regexp"
	"time"

	"siq-agent-security/edge/agent/canon"
	"siq-agent-security/edge/agent/installplan"
)

var errDiscoverySchedule = errors.New("discovery_schedule_unconfirmed")
var scheduleTimestamp = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$`)

type DiscoverySchedule struct {
	Schema     string `json:"schema_version"`
	ID         string `json:"schedule_id"`
	PlanDigest string `json:"installation_plan_sha256"`
	Identity   string `json:"device_identity"`
	StartsAt   string `json:"starts_at"`
	ExpiresAt  string `json:"expires_at"`
	Interval   int64  `json:"interval_seconds"`
	MaxRuns    int64  `json:"max_runs"`
	Purpose    string `json:"purpose"`
}

func parseDiscoverySchedule(raw []byte) (*DiscoverySchedule, error) {
	if len(raw) > 8192 {
		return nil, errDiscoverySchedule
	}
	fields := map[string]bool{"schema_version": true, "schedule_id": true, "installation_plan_sha256": true,
		"device_identity": true, "starts_at": true, "expires_at": true, "interval_seconds": true, "max_runs": true, "purpose": true}
	d := json.NewDecoder(bytes.NewReader(raw))
	start, err := d.Token()
	if err != nil || start != json.Delim('{') {
		return nil, errDiscoverySchedule
	}
	for d.More() {
		key, err := d.Token()
		name, ok := key.(string)
		if err != nil || !ok || !fields[name] {
			return nil, errDiscoverySchedule
		}
		delete(fields, name)
		var value json.RawMessage
		if d.Decode(&value) != nil || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return nil, errDiscoverySchedule
		}
	}
	end, err := d.Token()
	if err != nil || end != json.Delim('}') || len(fields) != 0 || d.Decode(new(any)) != io.EOF {
		return nil, errDiscoverySchedule
	}
	var result DiscoverySchedule
	if json.Unmarshal(raw, &result) != nil || !result.valid() {
		return nil, errDiscoverySchedule
	}
	return &result, nil
}

func (s DiscoverySchedule) valid() bool {
	if s.Schema != "enterprise-discovery-schedule/v1" || s.Purpose != "discovery_only" ||
		!regexp.MustCompile(`^eds-[a-f0-9]{32}$`).MatchString(s.ID) ||
		!regexp.MustCompile(`^[a-f0-9]{64}$`).MatchString(s.PlanDigest) ||
		!regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`).MatchString(s.Identity) ||
		s.Interval < 900 || s.Interval > 86400 || s.MaxRuns < 1 || s.MaxRuns > 2880 ||
		!scheduleTimestamp.MatchString(s.StartsAt) || !scheduleTimestamp.MatchString(s.ExpiresAt) {
		return false
	}
	start, e1 := time.Parse(time.RFC3339Nano, s.StartsAt)
	end, e2 := time.Parse(time.RFC3339Nano, s.ExpiresAt)
	return e1 == nil && e2 == nil && start.Year() >= 1 && end.Year() >= 1 && end.After(start) && end.Sub(start) <= 30*24*time.Hour
}

func (s DiscoverySchedule) digest() (string, error) {
	if !s.valid() {
		return "", errDiscoverySchedule
	}
	raw, err := canon.Marshal(map[string]any{"schema_version": s.Schema, "schedule_id": s.ID,
		"installation_plan_sha256": s.PlanDigest, "device_identity": s.Identity, "starts_at": s.StartsAt,
		"expires_at": s.ExpiresAt, "interval_seconds": s.Interval, "max_runs": s.MaxRuns, "purpose": s.Purpose})
	if err != nil {
		return "", errDiscoverySchedule
	}
	hash := sha256.Sum256(raw)
	return hex.EncodeToString(hash[:]), nil
}

type DiscoveryScheduleConfirmation struct {
	Schema        string `json:"schema_version"`
	ScheduleID    string `json:"schedule_id"`
	Identity      string `json:"device_identity"`
	Environment   string `json:"environment_id"`
	Origin        string `json:"control_plane_origin"`
	IntentDigest  string `json:"intent_digest"`
	PlanDigest    string `json:"installation_plan_sha256"`
	Revision      int64  `json:"expected_revision"`
	ConfirmedAt   string `json:"confirmed_at"`
	UserConfirmed bool   `json:"user_confirmed"`
	Signature     string `json:"signature"`
}

func (r DiscoveryScheduleConfirmation) signedBytes() ([]byte, error) {
	return canon.Marshal(map[string]any{"schema_version": r.Schema, "schedule_id": r.ScheduleID,
		"device_identity": r.Identity, "environment_id": r.Environment, "control_plane_origin": r.Origin,
		"intent_digest": r.IntentDigest, "installation_plan_sha256": r.PlanDigest, "expected_revision": r.Revision,
		"confirmed_at": r.ConfirmedAt, "user_confirmed": r.UserConfirmed})
}

// Preview binding validation has no signing side effect.
func checkScheduleBinding(state *State, schedule DiscoverySchedule, now time.Time) error {
	if state == nil || !schedule.valid() || schedule.Identity != state.DeviceIdentity {
		return errDiscoverySchedule
	}
	end, _ := time.Parse(time.RFC3339Nano, schedule.ExpiresAt)
	if !now.Before(end) || now.Year() < 1 || now.Year() > 9999 {
		return errDiscoverySchedule
	}
	storedDigest, err := compactPlanDigest(state.DiscoveryPlan)
	if err != nil || storedDigest != state.DiscoveryPlanSHA256 {
		return errDiscoverySchedule
	}
	plan, err := installplan.Parse(state.DiscoveryPlan)
	if err != nil || plan.EnvironmentID != state.EnvironmentID || plan.ControlPlaneOrigin != state.ControlPlaneURL {
		return errDiscoverySchedule
	}
	var value map[string]any
	d := json.NewDecoder(bytes.NewReader(state.DiscoveryPlan))
	d.UseNumber()
	if d.Decode(&value) != nil {
		return errDiscoverySchedule
	}
	canonical, err := canon.Marshal(value)
	if err != nil {
		return errDiscoverySchedule
	}
	hash := sha256.Sum256(canonical)
	if hex.EncodeToString(hash[:]) != schedule.PlanDigest {
		return errDiscoverySchedule
	}
	return nil
}

// Obtain explicit consent and persist the exact result before transport.
func prepareDiscoveryScheduleConfirmation(state *State, schedule DiscoverySchedule, revision int64, confirmed bool, now time.Time) (DiscoveryScheduleConfirmation, error) {
	var empty DiscoveryScheduleConfirmation
	if !confirmed || revision < 0 || checkScheduleBinding(state, schedule, now) != nil {
		return empty, errDiscoverySchedule
	}
	signer, err := NewSignerFromSeed(state.SignerSeed)
	if err != nil {
		return empty, errDiscoverySchedule
	}
	pub, err := signer.PublicKeyPEM()
	if err != nil || pub != state.PublicKeyPEM {
		return empty, errDiscoverySchedule
	}
	intentDigest, err := schedule.digest()
	if err != nil {
		return empty, errDiscoverySchedule
	}
	request := DiscoveryScheduleConfirmation{Schema: "edge-discovery-schedule-confirm/v1", ScheduleID: schedule.ID,
		Identity: state.DeviceIdentity, Environment: state.EnvironmentID, Origin: state.ControlPlaneURL,
		IntentDigest: intentDigest, PlanDigest: schedule.PlanDigest, Revision: revision, UserConfirmed: true,
		ConfirmedAt: now.UTC().Truncate(time.Microsecond).Format("2006-01-02T15:04:05.000000Z")}
	payload, err := request.signedBytes()
	if err != nil {
		return empty, errDiscoverySchedule
	}
	request.Signature, err = signer.Sign(payload)
	if err != nil {
		return empty, errDiscoverySchedule
	}
	return request, nil
}
