// Package pending records unsigned local decision failures (dev-spec §3.8.4).
// These are not receipts: Signed is always false until serve promotes them.
package pending

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

// SchemaID identifies the JSONL line contract.
const SchemaID = "pending_decision/v1"

// Record is one unsigned fail-closed / advisory line.
type Record struct {
	Schema          string `json:"schema"`
	RecordedAt      string `json:"recorded_at"`
	Platform        string `json:"platform"`
	Tool            string `json:"tool,omitempty"`
	SessionID       string `json:"session_id,omitempty"`
	EnforcementMode string `json:"enforcement_mode"`
	Outcome         string `json:"outcome"` // deny | allow
	Reason          string `json:"reason"`
	Signed          bool   `json:"signed"`
}

// Append writes one JSONL record under <stateDir>/pending/decisions.jsonl (0600).
func Append(stateDir string, rec Record) error {
	if stateDir == "" {
		return nil // no state dir → skip quietly (adapters may still decide)
	}
	dir := filepath.Join(stateDir, "pending")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	if rec.Schema == "" {
		rec.Schema = SchemaID
	}
	if rec.RecordedAt == "" {
		rec.RecordedAt = time.Now().UTC().Format(time.RFC3339Nano)
	}
	rec.Signed = false
	raw, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	path := filepath.Join(dir, "decisions.jsonl")
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer f.Close()
	if _, err := f.Write(append(raw, '\n')); err != nil {
		return err
	}
	return f.Sync()
}

// OutcomeForMode maps enforcement mode to the fail-closed table outcome.
func OutcomeForMode(mode string) string {
	if mode == "block" {
		return "deny"
	}
	return "allow"
}
