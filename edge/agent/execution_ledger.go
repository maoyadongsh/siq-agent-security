package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/edge/agent/canon"
)

// ExecLedgerRecord is one completed local outcome for a control-plane task
// (DEV10 / M-E5). Same task_id + same content digest → reuse Receipt; same
// task_id with a different digest → refuse (task_content_conflict).
type ExecLedgerRecord struct {
	TaskID        string  `json:"task_id"`
	ContentDigest string  `json:"content_digest"`
	Receipt       Receipt `json:"receipt"`
	RecordedAt    string  `json:"recorded_at"`
}

func execLedgerDir() (string, error) {
	dir, err := StateDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "exec_ledger"), nil
}

func execLedgerPath(taskID string) (string, error) {
	if taskID == "" || strings.ContainsAny(taskID, `/\:`) || strings.Contains(taskID, "..") {
		return "", fmt.Errorf("exec ledger: invalid task_id %q", taskID)
	}
	dir, err := execLedgerDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, taskID+".json"), nil
}

// TaskContentDigest is the sha256 hex of the canonical signed envelope
// (task_id/task_type/environment_id/payload/expires_at) — the same bytes
// VerifyTaskSignature authenticates. Signature itself is excluded.
func TaskContentDigest(t *Task) (string, error) {
	if t == nil {
		return "", fmt.Errorf("task content digest: nil task")
	}
	var payload any
	if len(t.Payload) > 0 && string(t.Payload) != "null" {
		var err error
		payload, err = canon.Decode(t.Payload)
		if err != nil {
			return "", fmt.Errorf("task content digest: payload: %w", err)
		}
	} else {
		payload = map[string]any{}
	}
	envelope := map[string]any{
		"task_id":        t.TaskID,
		"task_type":      t.TaskType,
		"environment_id": t.EnvironmentID,
		"payload":        payload,
		"expires_at":     t.ExpiresAt,
	}
	canonical, err := canon.Marshal(envelope)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(canonical)
	return hex.EncodeToString(sum[:]), nil
}

// LoadExecLedgerRecord returns the journaled outcome for taskID, or (nil, nil).
func LoadExecLedgerRecord(taskID string) (*ExecLedgerRecord, error) {
	path, err := execLedgerPath(taskID)
	if err != nil {
		return nil, err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var rec ExecLedgerRecord
	if err := json.Unmarshal(data, &rec); err != nil {
		return nil, fmt.Errorf("exec ledger: parse %s: %w", path, err)
	}
	if rec.TaskID == "" {
		rec.TaskID = taskID
	}
	return &rec, nil
}

// SaveExecLedgerRecord atomically journals a completed local outcome.
// Expiry failures must not be recorded (time-dependent).
func SaveExecLedgerRecord(t *Task, rcpt *Receipt) error {
	if t == nil || rcpt == nil || t.TaskID == "" {
		return fmt.Errorf("exec ledger: missing task or receipt")
	}
	if rcpt.ErrorCode == "expired" {
		return nil
	}
	digest, err := TaskContentDigest(t)
	if err != nil {
		return err
	}
	dir, err := execLedgerDir()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return fmt.Errorf("exec ledger: mkdir: %w", err)
	}
	path, err := execLedgerPath(t.TaskID)
	if err != nil {
		return err
	}
	rec := ExecLedgerRecord{
		TaskID:        t.TaskID,
		ContentDigest: digest,
		Receipt:       *rcpt,
		RecordedAt:    time.Now().UTC().Format(time.RFC3339),
	}
	data, err := json.MarshalIndent(rec, "", "  ")
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, ".ledger-*.tmp")
	if err != nil {
		return err
	}
	cleanup := func() {
		_ = tmp.Close()
		_ = os.Remove(tmp.Name())
	}
	if err := tmp.Chmod(0o600); err != nil {
		cleanup()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		cleanup()
		return err
	}
	if err := tmp.Sync(); err != nil {
		cleanup()
		return err
	}
	if err := tmp.Close(); err != nil {
		_ = os.Remove(tmp.Name())
		return err
	}
	if err := os.Rename(tmp.Name(), path); err != nil {
		_ = os.Remove(tmp.Name())
		return err
	}
	return nil
}

// LookupExecReuse returns a cached receipt when task_id was completed with the
// same content digest. Returns (nil, nil) when there is no record. Returns an
// error when the stored digest conflicts with the current task body.
func LookupExecReuse(t *Task) (*Receipt, error) {
	if t == nil || t.TaskID == "" {
		return nil, nil
	}
	rec, err := LoadExecLedgerRecord(t.TaskID)
	if err != nil || rec == nil {
		return nil, err
	}
	digest, err := TaskContentDigest(t)
	if err != nil {
		return nil, err
	}
	if rec.ContentDigest != digest {
		return nil, fmt.Errorf("task_content_conflict: task_id %q was completed with a different content digest", t.TaskID)
	}
	cp := rec.Receipt
	return &cp, nil
}
