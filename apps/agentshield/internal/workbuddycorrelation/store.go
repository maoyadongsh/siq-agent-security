// Package workbuddycorrelation persists bounded, untrusted hook correlations.
// None of these records authorizes execution: the server must recheck the hold.
package workbuddycorrelation

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

const MaxRecords = 2048
const MaxHistory = 64
const Limit = 16 << 10
const Window = 300 * time.Second

var ErrUnavailable = errors.New("workbuddy correlation unavailable; execution blocked")
var ErrUncertain = errors.New("workbuddy execution uncertain; do not replay")

type Record struct {
	SchemaVersion             string `json:"schema_version"`
	Kind                      string `json:"kind"`
	ScopeDigest               string `json:"scope_digest"`
	EffectDigest              string `json:"effect_digest"`
	SessionID                 string `json:"session_id"`
	AgentID                   string `json:"agent_id"`
	Tool                      string `json:"tool"`
	ToolCallID                string `json:"tool_call_id"`
	ParamsDigest              string `json:"params_digest"`
	CreatedAt                 string `json:"created_at"`
	ExpiresAt                 string `json:"expires_at"`
	Outcome                   string `json:"outcome,omitempty"`
	ActionID                  string `json:"action_id,omitempty"`
	DecisionReceiptID         string `json:"decision_receipt_id,omitempty"`
	OriginalToolCallID        string `json:"original_tool_call_id,omitempty"`
	OriginalDecisionReceiptID string `json:"original_decision_receipt_id,omitempty"`
	TaskID                    string `json:"task_id,omitempty"`
	RuntimeTaskID             string `json:"runtime_task_id,omitempty"`
}

type Transaction struct {
	Base     Record
	dir      string
	lockPath string
	lockInfo os.FileInfo
}

func digest(s string) string { sum := sha256.Sum256([]byte(s)); return hex.EncodeToString(sum[:]) }
func effect(scope, session, tool, params string) string {
	return digest("workbuddy-effect/v1\x00" + scope + "\x00" + session + "\x00" + tool + "\x00" + params)
}

func Lock(cfg adapters.WorkBuddyManagedConfig, req receipt.Request) (*Transaction, error) {
	if req.Platform != "workbuddy" || req.AgentID != cfg.AgentID || !runtimeidentity.ValidWorkBuddyCallID(req.ToolCallID) || !strings.HasPrefix(req.SessionID, "workbuddy-session/v1:") || !runtimeidentity.ValidWorkBuddyCallID(strings.Replace(req.SessionID, "workbuddy-session/v1:", "workbuddy-call/v1:", 1)) || req.Params == nil {
		return nil, ErrUnavailable
	}
	params, err := json.Marshal(req.Params)
	if err != nil || len(params) > adapters.WorkBuddyHookLimit {
		return nil, ErrUnavailable
	}
	scope := digest("workbuddy-hook-scope/v1\x00" + cfg.RuntimeIdentityID + "\x00" + cfg.InstanceID + "\x00" + cfg.AgentID)
	now := time.Now().UTC()
	tx := &Transaction{dir: filepath.Join(cfg.StateDir, "workbuddy-hooks", scope), Base: Record{SchemaVersion: "workbuddy-hook-correlation/v1", ScopeDigest: scope, SessionID: req.SessionID, AgentID: req.AgentID, Tool: req.Tool, ToolCallID: req.ToolCallID, ParamsDigest: digest(string(params)), CreatedAt: now.Format(time.RFC3339Nano), ExpiresAt: now.Add(Window).Format(time.RFC3339Nano)}}
	tx.Base.EffectDigest = effect(scope, req.SessionID, req.Tool, tx.Base.ParamsDigest)
	if err := statefs.MkdirAllPrivate(tx.dir); err != nil {
		return nil, ErrUnavailable
	}
	if _, err := tx.entries(); err != nil {
		return nil, err
	}
	// A scope lock also serializes capacity admission across different effects.
	// Contention fails closed immediately; it never extends the HTTP budget.
	tx.lockPath = filepath.Join(tx.dir, "lock")
	f, err := statefs.CreatePrivate(tx.lockPath)
	if err != nil {
		return nil, ErrUnavailable
	}
	tx.lockInfo, err = f.Stat()
	closeErr := f.Close()
	if err != nil || closeErr != nil {
		return nil, ErrUnavailable
	}
	return tx, nil
}

// Close removes only this invocation's temporary lock, never correlation data.
// A crashed invocation leaves a fail-closed lock; there is no stale-lock replay.
func (t *Transaction) Close() {
	path := t.lockPath
	if path == "" {
		return
	}
	t.lockPath = ""
	f, err := statefs.OpenPrivate(path)
	if err != nil {
		return
	}
	info, statErr := f.Stat()
	closeErr := f.Close()
	if statErr == nil && closeErr == nil && os.SameFile(t.lockInfo, info) {
		_ = statefs.Remove(path)
	}
}

func (t *Transaction) entries() ([]os.DirEntry, error) {
	f, err := statefs.OpenPrivateDir(t.dir)
	if err != nil {
		return nil, ErrUnavailable
	}
	defer f.Close()
	entries, err := f.ReadDir(MaxRecords + 1)
	if (err != nil && err != io.EOF) || len(entries) >= MaxRecords {
		return nil, ErrUnavailable
	}
	return entries, nil
}

func (t *Transaction) name(kind, call string) string {
	return kind + "-" + t.Base.EffectDigest + "-" + digest(call) + ".json"
}

func (t *Transaction) Write(kind string, record Record) error {
	if _, err := t.entries(); err != nil {
		return err
	}
	record.Kind = kind
	raw, err := json.Marshal(record)
	if err != nil || len(raw) > Limit || validate(raw, record, t.Base) != nil {
		return ErrUnavailable
	}
	if err := t.writeNew(t.name(kind, record.ToolCallID), raw); err != nil {
		return err
	}
	if kind == "pre" {
		return t.writeNew("call-"+digest(record.ToolCallID)+".json", raw)
	}
	return nil
}

func (t *Transaction) writeNew(name string, raw []byte) error {
	if _, err := t.entries(); err != nil {
		return err
	}
	f, err := statefs.CreatePrivate(filepath.Join(t.dir, name))
	if err != nil {
		return ErrUnavailable
	}
	_, err = f.Write(raw)
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil || closeErr != nil {
		return ErrUnavailable
	}
	return nil
}

var required = []string{"schema_version", "kind", "scope_digest", "effect_digest", "session_id", "agent_id", "tool", "tool_call_id", "params_digest", "created_at", "expires_at"}
var allowed = append(append([]string{}, required...), "outcome", "action_id", "decision_receipt_id", "original_tool_call_id", "original_decision_receipt_id", "task_id", "runtime_task_id")

func validate(raw []byte, record, base Record) error {
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return ErrUnavailable
	}
	for key, value := range fields {
		var text string
		if string(value) == "null" || json.Unmarshal(value, &text) != nil || !utf8.ValidString(text) || len(text) > 256 || strings.TrimSpace(text) != text || strings.IndexFunc(text, unicode.IsControl) >= 0 {
			return ErrUnavailable
		}
		if text == "" && key != "task_id" && key != "runtime_task_id" {
			return ErrUnavailable
		}
	}
	if record.SchemaVersion != "workbuddy-hook-correlation/v1" || record.ScopeDigest != base.ScopeDigest || record.EffectDigest != base.EffectDigest || record.SessionID != base.SessionID || record.AgentID != base.AgentID || record.Tool != base.Tool || record.ParamsDigest != base.ParamsDigest || !runtimeidentity.ValidWorkBuddyCallID(record.ToolCallID) {
		return ErrUnavailable
	}
	if record.OriginalToolCallID != "" && !runtimeidentity.ValidWorkBuddyCallID(record.OriginalToolCallID) {
		return ErrUnavailable
	}
	created, e1 := time.Parse(time.RFC3339Nano, record.CreatedAt)
	expires, e2 := time.Parse(time.RFC3339Nano, record.ExpiresAt)
	if e1 != nil || e2 != nil || !expires.After(created) || expires.Sub(created) > Window || created.After(time.Now().Add(time.Second)) {
		return ErrUnavailable
	}
	switch record.Kind {
	case "pre", "decision", "consume", "post", "complete", "terminal":
	default:
		return ErrUnavailable
	}
	if record.Kind == "decision" {
		switch record.Outcome {
		case "allow", "hold", "reserved":
			if record.ActionID == "" || record.DecisionReceiptID == "" {
				return ErrUnavailable
			}
		case "deny", "blocked":
		default:
			return ErrUnavailable
		}
		if record.Outcome == "reserved" && (record.OriginalToolCallID == "" || record.OriginalToolCallID == record.ToolCallID || record.OriginalDecisionReceiptID == "") {
			return ErrUnavailable
		}
	}
	return nil
}

func (t *Transaction) Read(kind, call string) (Record, error) {
	var record Record
	var guardRecord Record
	if kind == "pre" {
		guard, err := statefs.ReadPrivateFile(filepath.Join(t.dir, "call-"+digest(call)+".json"), Limit)
		if err != nil || adapters.DecodeWorkBuddyObject(guard, required, allowed, &record) != nil || validate(guard, record, t.Base) != nil || record.Kind != "pre" || record.ToolCallID != call {
			return Record{}, ErrUnavailable
		}
		guardRecord = record
	}
	raw, err := statefs.ReadPrivateFile(filepath.Join(t.dir, t.name(kind, call)), Limit)
	if err != nil {
		return record, err
	}
	if adapters.DecodeWorkBuddyObject(raw, required, allowed, &record) != nil || validate(raw, record, t.Base) != nil || record.Kind != kind || record.ToolCallID != call {
		return record, ErrUnavailable
	}
	if kind == "pre" && guardRecord != record {
		return Record{}, ErrUnavailable
	}
	return record, nil
}

func (t *Transaction) matches(kind string, expected Record) error {
	got, err := t.Read(kind, expected.ToolCallID)
	if err != nil {
		return err
	}
	got.Kind = expected.Kind
	if got != expected {
		return ErrUnavailable
	}
	return nil
}

// PriorHold refuses incomplete past pre/allow operations; no missing hint can
// silently turn a possibly consumed approval into a fresh execution.
func (t *Transaction) PriorHold() (*Record, error) {
	entries, err := t.entries()
	if err != nil {
		return nil, err
	}
	// Do not infer "no previous operation" from missing pre records. Every
	// other effect record and each scope-wide call guard must retain its pre.
	names := make(map[string]bool, len(entries))
	for _, entry := range entries {
		names[entry.Name()] = true
	}
	for _, entry := range entries {
		name := entry.Name()
		for _, kind := range []string{"decision", "consume", "post", "complete", "terminal"} {
			prefix := kind + "-" + t.Base.EffectDigest + "-"
			if strings.HasPrefix(name, prefix) && !names["pre-"+t.Base.EffectDigest+"-"+strings.TrimPrefix(name, prefix)] {
				return nil, ErrUncertain
			}
		}
		if strings.HasPrefix(name, "call-") {
			raw, err := statefs.ReadPrivateFile(filepath.Join(t.dir, name), Limit)
			var guard Record
			if err != nil || adapters.DecodeWorkBuddyObject(raw, required, allowed, &guard) != nil || validate(raw, guard, guard) != nil || guard.Kind != "pre" || guard.ScopeDigest != t.Base.ScopeDigest || guard.AgentID != t.Base.AgentID || guard.EffectDigest != effect(guard.ScopeDigest, guard.SessionID, guard.Tool, guard.ParamsDigest) || name != "call-"+digest(guard.ToolCallID)+".json" {
				return nil, ErrUnavailable
			}
			if guard.EffectDigest == t.Base.EffectDigest && !names[t.name("pre", guard.ToolCallID)] {
				return nil, ErrUncertain
			}
		}
	}
	var hold *Record
	count := 0
	for _, entry := range entries {
		if !strings.HasPrefix(entry.Name(), "pre-"+t.Base.EffectDigest+"-") {
			continue
		}
		count++
		if count >= MaxHistory {
			return nil, ErrUnavailable
		}
		raw, err := statefs.ReadPrivateFile(filepath.Join(t.dir, entry.Name()), Limit)
		if err != nil {
			return nil, ErrUnavailable
		}
		var pre Record
		if adapters.DecodeWorkBuddyObject(raw, required, allowed, &pre) != nil || validate(raw, pre, t.Base) != nil || pre.Kind != "pre" || entry.Name() != t.name("pre", pre.ToolCallID) {
			return nil, ErrUnavailable
		}
		if pre.ToolCallID == t.Base.ToolCallID {
			return nil, ErrUnavailable
		}
		if _, err := t.Read("pre", pre.ToolCallID); err != nil {
			return nil, ErrUncertain
		}
		d, err := t.Read("decision", pre.ToolCallID)
		if err != nil {
			return nil, ErrUncertain
		}
		switch d.Outcome {
		case "allow", "reserved":
			if err := t.matches("complete", d); err != nil {
				return nil, ErrUncertain
			}
		case "hold":
			if err := t.matches("terminal", d); err == nil {
				continue
			} else if !errors.Is(err, os.ErrNotExist) {
				return nil, ErrUnavailable
			}
			if err := t.matches("consume", d); err == nil {
				return nil, ErrUncertain
			} else if !errors.Is(err, os.ErrNotExist) {
				return nil, ErrUnavailable
			}
			expires, _ := time.Parse(time.RFC3339Nano, d.ExpiresAt)
			if !time.Now().Before(expires) {
				continue
			}
			if hold != nil {
				return nil, ErrUnavailable
			}
			copy := d
			hold = &copy
		}
	}
	return hold, nil
}

func (t *Transaction) Decision(outcome string, decision *receipt.Decision) Record {
	r := t.Base
	r.Outcome = outcome
	if decision != nil {
		r.ActionID = decision.Receipt.ActionID
		r.DecisionReceiptID = decision.Receipt.ReceiptID
		r.TaskID = decision.Receipt.TaskID
		r.RuntimeTaskID = decision.Receipt.RuntimeTaskID
		if decision.Hold != nil && decision.Hold.TimeoutMS > 0 && decision.Hold.TimeoutMS < int(Window/time.Millisecond) {
			at, _ := time.Parse(time.RFC3339Nano, r.CreatedAt)
			r.ExpiresAt = at.Add(time.Duration(decision.Hold.TimeoutMS) * time.Millisecond).Format(time.RFC3339Nano)
		}
	}
	return r
}
