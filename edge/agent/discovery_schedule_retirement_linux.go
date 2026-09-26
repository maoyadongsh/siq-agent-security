//go:build linux

package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"syscall"
	"unicode/utf8"
)

const scheduleRetirementPendingName = "discovery-schedule-retirement-pending.json"

type scheduleRetirementArchive struct {
	Schema  string                 `json:"schema_version"`
	Journal []byte                 `json:"journal_bytes"`
	Receipt []byte                 `json:"receipt_bytes"`
	Revoked DiscoveryScheduleState `json:"revoked_state"`
}

type scheduleRetirementPending struct {
	Schema   string `json:"schema_version"`
	Baseline string `json:"state_baseline"`
	Archive  string `json:"archive_sha256"`
}

// Any marker, including an incomplete or linked one, blocks normal startup and
// new confirmations. Only the explicit retirement recovery path may consume it.
func requireNoScheduleRetirement() error {
	dir, err := StateDir()
	if err != nil {
		return errDiscoverySchedule
	}
	if _, err := os.Lstat(filepath.Join(dir, scheduleRetirementPendingName)); !errors.Is(err, os.ErrNotExist) {
		return errDiscoverySchedule
	}
	return nil
}

func validScheduleAcknowledgement(raw []byte, journal *discoveryScheduleJournal) bool {
	if journal == nil || len(raw) > 8192 || !validRetirementJSON(raw) {
		return false
	}
	fields, ok := rotationJSONFields(raw, []string{"schema_version", "request_digest", "result"}, true)
	if !ok || !scheduleStateFields(fields["result"]) {
		return false
	}
	signed, err := journal.Request.signedBytes()
	hash := sha256.Sum256(signed)
	var receipt scheduleConfirmationReceipt
	return err == nil && json.Unmarshal(raw, &receipt) == nil && receipt.Schema == "edge-discovery-schedule-confirmed/v1" &&
		receipt.RequestDigest == hex.EncodeToString(hash[:]) && receipt.Result.Schema == "enterprise-discovery-schedule-state/v1" &&
		receipt.Result.ScheduleID == journal.Request.ScheduleID && receipt.Result.IntentDigest == journal.Request.IntentDigest &&
		receipt.Result.Status == "active" && receipt.Result.Revision > journal.Request.Revision
}

func validRetirementJSON(raw []byte) bool {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	return utf8.Valid(raw) && checkStateJSON(decoder, 0) == nil && decoder.Decode(new(any)) == io.EOF
}

// Read relative to the pinned private directory, including before unlinking a
// known original. Never follow a link, block on a FIFO or accept multiple links.
func readScheduleRetirementFile(dir *os.File, name string) ([]byte, error) {
	fd, err := syscall.Openat(int(dir.Fd()), name, syscall.O_RDONLY|syscall.O_NONBLOCK|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	file := os.NewFile(uintptr(fd), "schedule-retirement-read")
	defer file.Close()
	var before, after syscall.Stat_t
	const limit = 40000
	if syscall.Fstat(fd, &before) != nil || before.Mode&syscall.S_IFMT != syscall.S_IFREG ||
		before.Mode&0077 != 0 || before.Nlink != 1 || int(before.Uid) != os.Geteuid() || before.Size > limit {
		return nil, errDiscoverySchedule
	}
	raw, err := io.ReadAll(io.LimitReader(file, limit+1))
	if err != nil || len(raw) > limit || syscall.Fstat(fd, &after) != nil || before.Size != after.Size ||
		before.Mtim != after.Mtim || before.Ctim != after.Ctim || before.Mode != after.Mode || before.Nlink != after.Nlink ||
		before.Uid != after.Uid || !validRetirementJSON(raw) || file.Sync() != nil {
		return nil, errDiscoverySchedule
	}
	return raw, nil
}

// Exclusive, durable copies only. Existing or partial records are never repaired
// or overwritten. The caller pins the private state directory and holds its lock.
func writeScheduleRetirementFile(dir *os.File, name string, raw []byte) error {
	fd, err := syscall.Openat(int(dir.Fd()), name, syscall.O_WRONLY|syscall.O_CREAT|syscall.O_EXCL|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0600)
	if errors.Is(err, syscall.EEXIST) {
		prior, readErr := readScheduleRetirementFile(dir, name)
		if readErr != nil || !bytes.Equal(prior, raw) || dir.Sync() != nil {
			return errDiscoverySchedule
		}
		return nil // Reuse a complete identical durable copy; never repair one.
	}
	if err != nil {
		return errDiscoverySchedule
	}
	file := os.NewFile(uintptr(fd), "schedule-retirement-record")
	n, writeErr := file.Write(raw)
	syncErr := file.Sync()
	closeErr := file.Close()
	if writeErr != nil || n != len(raw) || syncErr != nil || closeErr != nil || dir.Sync() != nil {
		return errDiscoverySchedule
	}
	return nil
}

// Prepare only: preserve originals, copy their exact bytes to immutable history,
// then publish a recovery marker. No cleanup, new consent or service operations.
// The caller must hold the device task lock and obtain explicit digest consent.
func prepareScheduleRetirement(ctx context.Context, state *State, client *Client, confirmedDigest string) (string, error) {
	if ctx.Err() != nil || client == nil || requireNoScheduleRetirement() != nil {
		return "", errDiscoverySchedule
	}
	current, err := loadRotationState()
	if err != nil || state == nil || rotationStateBaseline(current) != rotationStateBaseline(state) || current.Secret != state.Secret {
		return "", errDiscoverySchedule
	}
	journal, err := readScheduleJournal(state)
	if err != nil || confirmedDigest != journal.Request.IntentDigest {
		return "", errDiscoverySchedule
	}
	path, err := scheduleJournalPath()
	if err != nil {
		return "", errDiscoverySchedule
	}
	original, err := readDeviceState(path)
	var reread discoveryScheduleJournal
	if err != nil || len(original) > 16384 || json.Unmarshal(original, &reread) != nil || reread.validate(state) != nil ||
		reread.Request != journal.Request || !bytes.Equal(reread.Intent, journal.Intent) {
		return "", errDiscoverySchedule
	}
	ack, err := readDeviceState(filepath.Join(filepath.Dir(path), "discovery-schedule-confirmed.json"))
	if err != nil {
		// Unknown confirmation results can be retired only after online revocation;
		// an existing malformed receipt is not equivalent to an absent receipt.
		if !errors.Is(err, os.ErrNotExist) {
			return "", errDiscoverySchedule
		}
		ack = []byte{}
	} else if !validScheduleAcknowledgement(ack, journal) {
		return "", errDiscoverySchedule
	}
	revoked, err := client.verifyRevokedSchedule(ctx, state, journal)
	if err != nil || ctx.Err() != nil {
		return "", errDiscoverySchedule
	}
	record := scheduleRetirementArchive{Schema: "edge-discovery-schedule-history/v1", Journal: original, Receipt: ack, Revoked: *revoked}
	raw, err := json.Marshal(record)
	if err != nil {
		return "", errDiscoverySchedule
	}
	hash := sha256.Sum256(raw)
	digest := hex.EncodeToString(hash[:])
	name := "discovery-schedule-history-" + digest + ".json"
	dir, err := scheduleStateDirectory()
	if err != nil {
		return "", errDiscoverySchedule
	}
	defer dir.Close()
	if err := writeScheduleRetirementFile(dir, name, raw); err != nil {
		return "", errDiscoverySchedule
	}
	stored, err := readDeviceState(filepath.Join(filepath.Dir(path), name))
	if err != nil || !bytes.Equal(stored, raw) || ctx.Err() != nil {
		return "", errDiscoverySchedule
	}
	marker, err := json.Marshal(scheduleRetirementPending{Schema: "edge-discovery-schedule-retirement-pending/v1",
		Baseline: rotationStateBaseline(state), Archive: digest})
	if err != nil || writeScheduleRetirementFile(dir, scheduleRetirementPendingName, marker) != nil {
		return "", errDiscoverySchedule
	}
	stored, err = readDeviceState(filepath.Join(filepath.Dir(path), scheduleRetirementPendingName))
	if err != nil || !bytes.Equal(stored, marker) || ctx.Err() != nil {
		return "", errDiscoverySchedule
	}
	return digest, nil
}

func readPendingScheduleRetirement(dir *os.File, state *State) (*scheduleRetirementArchive, *discoveryScheduleJournal, []byte, error) {
	raw, err := readScheduleRetirementFile(dir, scheduleRetirementPendingName)
	if err != nil {
		return nil, nil, nil, errDiscoverySchedule
	}
	if _, ok := rotationJSONFields(raw, []string{"schema_version", "state_baseline", "archive_sha256"}, true); !ok {
		return nil, nil, nil, errDiscoverySchedule
	}
	var marker scheduleRetirementPending
	if state == nil || json.Unmarshal(raw, &marker) != nil || marker.Schema != "edge-discovery-schedule-retirement-pending/v1" ||
		marker.Baseline != rotationStateBaseline(state) || !regexp.MustCompile(`^[a-f0-9]{64}$`).MatchString(marker.Archive) {
		return nil, nil, nil, errDiscoverySchedule
	}
	archive, err := readScheduleRetirementFile(dir, "discovery-schedule-history-"+marker.Archive+".json")
	hash := sha256.Sum256(archive)
	if err != nil || hex.EncodeToString(hash[:]) != marker.Archive {
		return nil, nil, nil, errDiscoverySchedule
	}
	fields, ok := rotationJSONFields(archive, []string{"schema_version", "journal_bytes", "receipt_bytes", "revoked_state"}, true)
	if !ok || !scheduleStateFields(fields["revoked_state"]) {
		return nil, nil, nil, errDiscoverySchedule
	}
	var record scheduleRetirementArchive
	if json.Unmarshal(archive, &record) != nil || record.Schema != "edge-discovery-schedule-history/v1" {
		return nil, nil, nil, errDiscoverySchedule
	}
	journal, err := parseScheduleJournal(state, record.Journal)
	if err != nil || (len(record.Receipt) != 0 && !validScheduleAcknowledgement(record.Receipt, journal)) ||
		record.Revoked.Schema != "enterprise-discovery-schedule-state/v1" || record.Revoked.Status != "revoked" ||
		record.Revoked.ScheduleID != journal.Request.ScheduleID || record.Revoked.IntentDigest != journal.Request.IntentDigest ||
		record.Revoked.Revision <= journal.Request.Revision {
		return nil, nil, nil, errDiscoverySchedule
	}
	return &record, journal, raw, nil
}

// Caller holds the device lock. Originals already absent are an allowed crash
// point; present originals must exactly match the durable, validated archive.
func removeArchivedScheduleFile(dir *os.File, name string, expected []byte) error {
	raw, err := readScheduleRetirementFile(dir, name)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil || len(expected) == 0 || !bytes.Equal(raw, expected) {
		return errDiscoverySchedule
	}
	if syscall.Unlinkat(int(dir.Fd()), name) != nil || dir.Sync() != nil {
		return errDiscoverySchedule
	}
	return nil
}

// Complete or resume only the archived transaction, after fresh online
// revocation verification. This does not create or confirm a replacement plan.
func finishScheduleRetirement(ctx context.Context, state *State, client *Client, confirmedDigest string) error {
	if ctx.Err() != nil || state == nil || client == nil {
		return errDiscoverySchedule
	}
	current, err := loadRotationState()
	if err != nil || rotationStateBaseline(current) != rotationStateBaseline(state) || current.Secret != state.Secret {
		return errDiscoverySchedule
	}
	dir, err := scheduleStateDirectory()
	if err != nil {
		return errDiscoverySchedule
	}
	defer dir.Close()
	record, journal, markerRaw, err := readPendingScheduleRetirement(dir, state)
	if err != nil || confirmedDigest != journal.Request.IntentDigest {
		return errDiscoverySchedule
	}
	revoked, err := client.verifyRevokedSchedule(ctx, state, journal)
	if err != nil || revoked.Revision < record.Revoked.Revision || ctx.Err() != nil {
		return errDiscoverySchedule
	}
	// Check both before removing either; unknown local replacement stays intact.
	for name, expected := range map[string][]byte{scheduleJournalName: record.Journal, "discovery-schedule-confirmed.json": record.Receipt} {
		raw, err := readScheduleRetirementFile(dir, name)
		if !errors.Is(err, os.ErrNotExist) && (err != nil || len(expected) == 0 || !bytes.Equal(raw, expected)) {
			return errDiscoverySchedule
		}
	}
	if ctx.Err() != nil || removeArchivedScheduleFile(dir, "discovery-schedule-confirmed.json", record.Receipt) != nil ||
		removeArchivedScheduleFile(dir, scheduleJournalName, record.Journal) != nil {
		return errDiscoverySchedule
	}
	var marker scheduleRetirementPending
	if json.Unmarshal(markerRaw, &marker) != nil {
		return errDiscoverySchedule
	}
	if writeScheduleRetirementFile(dir, "discovery-schedule-retired-"+marker.Archive+".json", markerRaw) != nil || ctx.Err() != nil {
		return errDiscoverySchedule
	}
	// Completion is durable before removing the in-progress marker. Neither
	// immutable history nor its completion record is ever deleted.
	return removeArchivedScheduleFile(dir, scheduleRetirementPendingName, markerRaw)
}
