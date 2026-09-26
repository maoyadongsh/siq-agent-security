//go:build linux

package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

const scheduleJournalName = "discovery-schedule-pending.json"

type discoveryScheduleJournal struct {
	Schema   string                        `json:"schema_version"`
	Baseline string                        `json:"state_baseline"`
	Intent   json.RawMessage               `json:"intent"`
	Request  DiscoveryScheduleConfirmation `json:"request"`
}

func (j *discoveryScheduleJournal) validate(state *State) error {
	if state == nil || j.Schema != "edge-discovery-schedule-pending/v1" || j.Baseline == "" || j.Baseline != rotationStateBaseline(state) {
		return errDiscoverySchedule
	}
	schedule, err := parseDiscoverySchedule(j.Intent)
	if err != nil || !j.Request.valid() {
		return errDiscoverySchedule
	}
	timestamp, err := time.Parse(time.RFC3339Nano, j.Request.ConfirmedAt)
	if err != nil {
		return errDiscoverySchedule
	}
	expected, err := prepareDiscoveryScheduleConfirmation(state, *schedule, j.Request.Revision, true, timestamp)
	if err != nil || expected != j.Request {
		return errDiscoverySchedule
	}
	return nil
}

func scheduleJournalPath() (string, error) {
	dir, err := StateDir()
	if err != nil {
		return "", errDiscoverySchedule
	}
	return filepath.Join(dir, scheduleJournalName), nil
}

func readScheduleJournal(state *State) (*discoveryScheduleJournal, error) {
	path, err := scheduleJournalPath()
	if err != nil {
		return nil, errDiscoverySchedule
	}
	raw, err := readDeviceState(path)
	if err != nil || len(raw) > 16384 {
		return nil, errDiscoverySchedule
	}
	return parseScheduleJournal(state, raw)
}

func parseScheduleJournal(state *State, raw []byte) (*discoveryScheduleJournal, error) {
	if len(raw) > 16384 || !validRetirementJSON(raw) {
		return nil, errDiscoverySchedule
	}
	fields, ok := rotationJSONFields(raw, []string{"schema_version", "state_baseline", "intent", "request"}, true)
	if !ok {
		return nil, errDiscoverySchedule
	}
	if _, ok := rotationJSONFields(fields["request"], []string{"schema_version", "schedule_id", "device_identity", "environment_id",
		"control_plane_origin", "intent_digest", "installation_plan_sha256", "expected_revision", "confirmed_at", "user_confirmed", "signature"}, true); !ok {
		return nil, errDiscoverySchedule
	}
	var journal discoveryScheduleJournal
	if json.Unmarshal(raw, &journal) != nil || journal.validate(state) != nil {
		return nil, errDiscoverySchedule
	}
	return &journal, nil
}

// Pin the existing private state directory. Never create or repair ancestors.
func scheduleStateDirectory() (*os.File, error) {
	path, err := StateDir()
	if err != nil || !filepath.IsAbs(path) || filepath.Clean(path) != path || path == "/" {
		return nil, errDiscoverySchedule
	}
	fd, err := syscall.Open("/", syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, errDiscoverySchedule
	}
	for _, part := range strings.Split(strings.TrimPrefix(path, "/"), "/") {
		next, err := syscall.Openat(fd, part, syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
		syscall.Close(fd)
		if err != nil {
			return nil, errDiscoverySchedule
		}
		fd = next
		var info syscall.Stat_t
		if syscall.Fstat(fd, &info) != nil || (int(info.Uid) != os.Geteuid() && info.Uid != 0) ||
			(info.Mode&0022 != 0 && !(info.Uid == 0 && info.Mode&syscall.S_ISVTX != 0)) {
			syscall.Close(fd)
			return nil, errDiscoverySchedule
		}
	}
	if !privateSkillDirectory(fd) {
		syscall.Close(fd)
		return nil, errDiscoverySchedule
	}
	return os.NewFile(uintptr(fd), "schedule-state"), nil
}

// Caller must hold the device task lock. Any incomplete file remains for review;
// no request may be sent until this returns a validated, synchronized journal.
func prepareScheduleJournal(state *State, rawIntent []byte, revision int64, confirmed bool, now time.Time) (*discoveryScheduleJournal, error) {
	if requireNoScheduleRetirement() != nil {
		return nil, errDiscoverySchedule
	}
	current, err := loadRotationState()
	if err != nil || state == nil || rotationStateBaseline(current) != rotationStateBaseline(state) || current.Secret != state.Secret {
		return nil, errDiscoverySchedule
	}
	schedule, err := parseDiscoverySchedule(rawIntent)
	if err != nil {
		return nil, errDiscoverySchedule
	}
	request, err := prepareDiscoveryScheduleConfirmation(state, *schedule, revision, confirmed, now)
	if err != nil {
		return nil, errDiscoverySchedule
	}
	journal := &discoveryScheduleJournal{Schema: "edge-discovery-schedule-pending/v1", Baseline: rotationStateBaseline(state),
		Intent: append(json.RawMessage(nil), rawIntent...), Request: request}
	if journal.validate(state) != nil {
		return nil, errDiscoverySchedule
	}
	raw, err := json.Marshal(journal)
	if err != nil || len(raw) > 16384 {
		return nil, errDiscoverySchedule
	}
	dir, err := scheduleStateDirectory()
	if err != nil {
		return nil, errDiscoverySchedule
	}
	defer dir.Close()
	fd, err := syscall.Openat(int(dir.Fd()), scheduleJournalName, syscall.O_WRONLY|syscall.O_CREAT|syscall.O_EXCL|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0600)
	if err != nil {
		return nil, errDiscoverySchedule
	}
	file := os.NewFile(uintptr(fd), "schedule-pending")
	n, writeErr := file.Write(raw)
	syncErr := file.Sync()
	closeErr := file.Close()
	if writeErr != nil || n != len(raw) || syncErr != nil || closeErr != nil || dir.Sync() != nil {
		return nil, errDiscoverySchedule
	}
	return readScheduleJournal(state)
}
