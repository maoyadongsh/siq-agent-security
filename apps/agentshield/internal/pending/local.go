package pending

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"regexp"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/stateformat"
)

var ErrLocalRecord = errors.New("pending: invalid local failure record")
var localReason = regexp.MustCompile(`^[a-z][a-z0-9_]{1,127}$`)
var localDigest = regexp.MustCompile(`^[a-f0-9]{64}$`)

func localText(value string, limit int) bool {
	return value != "" && len(value) <= limit && utf8.ValidString(value) && strings.TrimSpace(value) == value && strings.IndexFunc(value, unicode.IsControl) < 0
}

func localID(prefix, value string) string {
	digest := sha256.Sum256([]byte(value))
	return prefix + hex.EncodeToString(digest[:])
}

func ValidateLocalRecord(rec Record) error {
	if rec.Schema != LocalSchemaID {
		return nil
	} // Retain legacy reader semantics.
	if rec.Platform != "workbuddy" || rec.Origin != "local_hook" || rec.Signed || !localText(rec.Reason, 512) || !localReason.MatchString(rec.ReasonCode) {
		return ErrLocalRecord
	}
	if rec.EnforcementMode != "block" && rec.EnforcementMode != "warn" && rec.EnforcementMode != "audit_only" {
		return ErrLocalRecord
	}
	if _, err := time.Parse(time.RFC3339Nano, rec.RecordedAt); err != nil {
		return ErrLocalRecord
	}
	switch rec.Stage {
	case "parse", "bootstrap", "enrollment", "correlation", "decision", "observation":
	default:
		return ErrLocalRecord
	}
	if rec.Outcome != "deny" && !(rec.Outcome == "unconfirmed" && rec.Stage == "observation") {
		return ErrLocalRecord
	}
	if rec.Tool != "" && !localText(rec.Tool, 256) {
		return ErrLocalRecord
	}
	hasIdentity := rec.SessionID != "" || rec.ToolCallID != "" || rec.NativeSessionID != "" || rec.NativeCallID != "" || rec.ActionDigest != ""
	if hasIdentity {
		if rec.Stage == "parse" || !localText(rec.NativeSessionID, 256) || !localText(rec.NativeCallID, 256) || !localText(rec.Tool, 256) || !localDigest.MatchString(rec.ActionDigest) {
			return ErrLocalRecord
		}
		if rec.SessionID != localID("workbuddy-session/v1:", "workbuddy-native-session/v1\x00"+rec.NativeSessionID) || rec.ToolCallID != localID("workbuddy-call/v1:", "workbuddy-native-call/v1\x00"+rec.NativeSessionID+"\x00"+rec.NativeCallID) {
			return ErrLocalRecord
		}
	}
	return nil
}

func decodeLocalRecord(raw []byte, rec *Record) error {
	if len(raw) > LocalRecordLimit {
		return ErrLocalRecord
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil || fields == nil {
		return ErrLocalRecord
	}
	allowed := map[string]bool{}
	for _, name := range []string{"schema", "recorded_at", "platform", "tool", "session_id", "enforcement_mode", "outcome", "reason", "signed", "origin", "stage", "reason_code", "native_session_id", "native_call_id", "tool_call_id", "action_digest"} {
		allowed[name] = true
	}
	var keys []string
	for name := range fields {
		if !allowed[name] {
			return ErrLocalRecord
		}
		keys = append(keys, name)
	}
	for _, name := range []string{"schema", "recorded_at", "platform", "enforcement_mode", "outcome", "reason", "signed", "origin", "stage", "reason_code"} {
		if _, ok := fields[name]; !ok {
			return ErrLocalRecord
		}
	}
	if stateformat.DecodeObject(raw, keys, rec) != nil {
		return ErrLocalRecord
	}
	return ValidateLocalRecord(*rec)
}
