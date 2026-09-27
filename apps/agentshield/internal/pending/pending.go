// Package pending records unsigned local decision failures (dev-spec §3.8.4).
// These are not receipts: Signed stays false, including inside a signed v2
// promotion that records the original local event's unverified provenance.
package pending

import (
	"encoding/json"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/statefs"
	"time"
)

// SchemaID identifies the JSONL line contract.
const SchemaID = "pending_decision/v1"
const LocalSchemaID = "pending_decision/v2"
const LocalRecordLimit = 8192

// Record is one unsigned fail-closed / advisory line.
type Record struct {
	Schema          string `json:"schema"`
	RecordedAt      string `json:"recorded_at"`
	Platform        string `json:"platform"`
	Tool            string `json:"tool,omitempty"`
	SessionID       string `json:"session_id,omitempty"`
	EnforcementMode string `json:"enforcement_mode"`
	Outcome         string `json:"outcome"` // v1 deny|allow; v2 deny|unconfirmed
	Reason          string `json:"reason"`
	Signed          bool   `json:"signed"`
	Origin          string `json:"origin,omitempty"`
	Stage           string `json:"stage,omitempty"`
	ReasonCode      string `json:"reason_code,omitempty"`
	NativeSessionID string `json:"native_session_id,omitempty"`
	NativeCallID    string `json:"native_call_id,omitempty"`
	ToolCallID      string `json:"tool_call_id,omitempty"`
	ActionDigest    string `json:"action_digest,omitempty"`
}

// Append writes one JSONL record under <stateDir>/pending/decisions.jsonl (0600).
func Append(stateDir string, rec Record) error {
	if stateDir == "" {
		return nil // no state dir → skip quietly (adapters may still decide)
	}
	dir := filepath.Join(stateDir, "pending")
	if err := statefs.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	if rec.Schema == "" {
		rec.Schema = SchemaID
	}
	if rec.RecordedAt == "" {
		rec.RecordedAt = time.Now().UTC().Format(time.RFC3339Nano)
	}
	rec.Signed = false
	if err := ValidateLocalRecord(rec); err != nil {
		return err
	}
	raw, err := json.Marshal(rec)
	if err != nil {
		return err
	}
	if rec.Schema == LocalSchemaID && len(raw) > LocalRecordLimit {
		return ErrLocalRecord
	}
	path := filepath.Join(dir, "decisions.jsonl")
	f, err := statefs.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
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
