package adapters

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/url"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/pending"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

const WorkBuddyHookLimit = 1 << 20

var errWorkBuddyWire = errors.New("workbuddy managed hook: invalid document")
var workBuddyIdentity = regexp.MustCompile(`^ri-[a-f0-9]{32}$`)

// WorkBuddyManagedConfig contains references, never a bearer or signing key.
type WorkBuddyManagedConfig struct {
	SchemaVersion     string `json:"schema_version"`
	RuntimeIdentityID string `json:"runtime_identity_id"`
	InstanceID        string `json:"instance_id"`
	AgentID           string `json:"agent_id"`
	CredentialPath    string `json:"credential_path"`
	Endpoint          string `json:"endpoint"`
	EnforcementMode   string `json:"enforcement_mode"`
	StateDir          string `json:"state_dir"`
}

// DecodeWorkBuddyObject rejects duplicate keys recursively, aliases, trailing
// documents and excessive nesting before typed decoding can discard ambiguity.
// Nested tool input keys remain data; only the outer protocol has a closed set.
func DecodeWorkBuddyObject(raw []byte, required, allowed []string, out any) error {
	if len(raw) == 0 || len(raw) > WorkBuddyHookLimit || !utf8.Valid(raw) {
		return errWorkBuddyWire
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if err := workBuddyJSONValue(d, 0); err != nil {
		return err
	}
	if _, err := d.Token(); err != io.EOF {
		return errWorkBuddyWire
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil || fields == nil {
		return errWorkBuddyWire
	}
	for _, key := range required {
		if _, ok := fields[key]; !ok {
			return errWorkBuddyWire
		}
	}
	for key := range fields {
		found := false
		for _, candidate := range allowed {
			found = found || key == candidate
		}
		if !found {
			return errWorkBuddyWire
		}
	}
	d = json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	d.DisallowUnknownFields()
	if d.Decode(out) != nil {
		return errWorkBuddyWire
	}
	return nil
}

func workBuddyJSONValue(d *json.Decoder, depth int) error {
	if depth > 64 {
		return errWorkBuddyWire
	}
	v, err := d.Token()
	if err != nil {
		return errWorkBuddyWire
	}
	delim, nested := v.(json.Delim)
	if !nested {
		return nil
	}
	switch delim {
	case '{':
		seen := map[string]bool{}
		for d.More() {
			key, err := d.Token()
			name, ok := key.(string)
			if err != nil || !ok || seen[name] {
				return errWorkBuddyWire
			}
			seen[name] = true
			if err := workBuddyJSONValue(d, depth+1); err != nil {
				return err
			}
		}
		end, err := d.Token()
		if err != nil || end != json.Delim('}') {
			return errWorkBuddyWire
		}
	case '[':
		for d.More() {
			if err := workBuddyJSONValue(d, depth+1); err != nil {
				return err
			}
		}
		end, err := d.Token()
		if err != nil || end != json.Delim(']') {
			return errWorkBuddyWire
		}
	default:
		return errWorkBuddyWire
	}
	return nil
}

func DecodeWorkBuddyManagedConfig(raw []byte, path, stateDir string) (WorkBuddyManagedConfig, error) {
	var c WorkBuddyManagedConfig
	fields := []string{"schema_version", "runtime_identity_id", "instance_id", "agent_id", "credential_path", "endpoint", "enforcement_mode", "state_dir"}
	if len(raw) > 16<<10 || DecodeWorkBuddyObject(raw, fields, fields, &c) != nil {
		return c, errWorkBuddyWire
	}
	if c.SchemaVersion != "workbuddy-managed-hook/v1" || !workBuddyIdentity.MatchString(c.RuntimeIdentityID) ||
		len(c.StateDir) > 4096 || len(c.CredentialPath) > 4096 || len(c.Endpoint) > 512 ||
		!filepath.IsAbs(path) || filepath.Clean(path) != path || filepath.Base(path) != product.Name+".json" ||
		!filepath.IsAbs(stateDir) || filepath.Clean(stateDir) != stateDir || c.StateDir != stateDir ||
		c.InstanceID != hermeshome.Identifier(filepath.Dir(path)) || c.AgentID != "hri-"+strings.TrimPrefix(c.InstanceID, "hi-") ||
		c.CredentialPath != filepath.Join(stateDir, "runtime-identity-secrets", c.RuntimeIdentityID+".token") {
		return c, errWorkBuddyWire
	}
	if c.EnforcementMode != "block" && c.EnforcementMode != "warn" && c.EnforcementMode != "audit_only" {
		return c, errWorkBuddyWire
	}
	u, err := url.Parse(c.Endpoint)
	if err != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" || u.User != nil || u.Path != "" || u.RawQuery != "" || u.Fragment != "" || u.ForceQuery {
		return c, errWorkBuddyWire
	}
	port, err := strconv.Atoi(u.Port())
	if err != nil || port < 1 || port > 65535 || c.Endpoint != "http://127.0.0.1:"+strconv.Itoa(port) {
		return c, errWorkBuddyWire
	}
	return c, nil
}

type WorkBuddyManagedInput struct {
	HookEventName  string         `json:"hook_event_name"`
	SessionID      string         `json:"session_id"`
	ToolUseID      string         `json:"tool_use_id"`
	CallID         string         `json:"call_id"`
	ToolName       string         `json:"tool_name"`
	ToolInput      map[string]any `json:"tool_input"`
	ToolResponse   any            `json:"tool_response,omitempty"`
	Cwd            string         `json:"cwd,omitempty"`
	TranscriptPath string         `json:"transcript_path,omitempty"`
	PermissionMode string         `json:"permission_mode,omitempty"`
	AgentID        string         `json:"agent_id,omitempty"`
	AgentType      string         `json:"agent_type,omitempty"`
	GenerationID   string         `json:"generation_id,omitempty"`
	Model          string         `json:"model,omitempty"`
	Client         string         `json:"client,omitempty"`
	Version        string         `json:"version,omitempty"`
}

func workBuddyText(value string, max int, optional bool) bool {
	if !utf8.ValidString(value) || len(value) > max || (!optional && value == "") || strings.TrimSpace(value) != value {
		return false
	}
	for _, r := range value {
		if unicode.IsControl(r) {
			return false
		}
	}
	return true
}

func ParseWorkBuddyManagedInput(in io.Reader) (WorkBuddyManagedInput, error) {
	var ev WorkBuddyManagedInput
	raw, err := io.ReadAll(io.LimitReader(in, WorkBuddyHookLimit+1))
	if err != nil {
		return ev, errWorkBuddyWire
	}
	required := []string{"hook_event_name", "session_id", "tool_use_id", "call_id", "tool_name", "tool_input"}
	metadata := []string{"cwd", "transcript_path", "permission_mode", "agent_id", "agent_type", "generation_id", "model", "client", "version"}
	allowed := append(append(append([]string{}, required...), "tool_response"), metadata...)
	if DecodeWorkBuddyObject(raw, required, allowed, &ev) != nil || ev.ToolInput == nil {
		return ev, errWorkBuddyWire
	}
	if ev.HookEventName != "PreToolUse" && ev.HookEventName != "PostToolUse" {
		return ev, errWorkBuddyWire
	}
	for _, v := range []string{ev.SessionID, ev.ToolUseID, ev.CallID, ev.ToolName} {
		if !workBuddyText(v, 256, false) {
			return ev, errWorkBuddyWire
		}
	}
	if ev.ToolUseID != ev.CallID {
		return ev, errWorkBuddyWire
	}
	var fields map[string]json.RawMessage
	_ = json.Unmarshal(raw, &fields)
	if ev.HookEventName == "PostToolUse" {
		if _, exists := fields["tool_response"]; !exists {
			return ev, errWorkBuddyWire
		}
	}
	for _, name := range metadata {
		if v, ok := fields[name]; ok {
			var text string
			if bytes.Equal(bytes.TrimSpace(v), []byte("null")) || json.Unmarshal(v, &text) != nil || !workBuddyText(text, 4096, true) {
				return ev, errWorkBuddyWire
			}
		}
	}
	return ev, nil
}

type WorkBuddyManagedDecider interface {
	Decider
	Enroll(session string) error
}

// WorkBuddyManagedFailure distinguishes a local refusal from a possibly
// consumed server reservation without inventing a decision receipt.
type WorkBuddyManagedFailure struct {
	Uncertain bool
	Code      string
}

func (e *WorkBuddyManagedFailure) Error() string { return "managed WorkBuddy correlation unavailable" }

// These fixed categories never expose a transport error, URL, or bearer.
type WorkBuddyServiceFailure struct{ Code string }

func (e *WorkBuddyServiceFailure) Error() string { return "managed service unavailable" }

type WorkBuddyEnrollmentDeadline struct{ BeforeRequest bool }

func (e *WorkBuddyEnrollmentDeadline) Error() string { return "managed enrollment deadline" }

// WorkBuddyManagedHook has no default session/agent or advisory transport
// fallback. A valid server policy allow expresses no opinion to the host.
func WorkBuddyManagedHook(in io.Reader, d WorkBuddyManagedDecider, agentID, mode, stateDir string) WorkBuddyOutput {
	ev, err := ParseWorkBuddyManagedInput(in)
	if err != nil {
		return workBuddyLocalFailure(nil, mode, stateDir, "parse", "workbuddy_input_invalid", "invalid managed hook input")
	}
	fail := func(stage, code, reason string) WorkBuddyOutput {
		return workBuddyLocalFailure(&ev, mode, stateDir, stage, code, reason)
	}
	session, err := runtimeidentity.WorkBuddySessionID(ev.SessionID)
	if err != nil {
		return workBuddyLocalFailure(nil, mode, stateDir, "parse", "workbuddy_session_invalid", "invalid native session")
	}
	call, err := runtimeidentity.WorkBuddyCallID(ev.SessionID, ev.CallID)
	if err != nil {
		return workBuddyLocalFailure(nil, mode, stateDir, "parse", "workbuddy_call_invalid", "invalid native call")
	}
	req := receipt.Request{Platform: "workbuddy", SessionID: session, AgentID: agentID, Tool: ev.ToolName, ToolCallID: call, Params: ev.ToolInput, Context: map[string]any{"cwd": ev.Cwd, "permission_mode": ev.PermissionMode}}
	var out WorkBuddyOutput
	out.HookSpecificOutput.HookEventName = ev.HookEventName
	if ev.HookEventName == "PostToolUse" {
		if d != nil {
			text, ok := ev.ToolResponse.(string)
			if !ok {
				raw, _ := json.Marshal(ev.ToolResponse)
				text = string(raw)
			}
			if len(text) > 64<<10 {
				text = text[:64<<10]
				for !utf8.ValidString(text) {
					text = text[:len(text)-1]
				}
			}
			if d.Observe(req, text) == nil {
				return out
			}
		}
		return fail("observation", "workbuddy_observation_unconfirmed", "managed observation unavailable")
	}
	if d == nil || !strings.HasPrefix(agentID, "hri-") {
		return fail("bootstrap", "workbuddy_configuration_unavailable", "managed configuration or credential unavailable; run adapter diagnosis (workbuddy-preflight)")
	}
	if err := d.Enroll(session); err != nil {
		reason := "managed session enrollment unavailable"
		code := "workbuddy_enrollment_unavailable"
		var service *WorkBuddyServiceFailure
		if errors.As(err, &service) {
			switch service.Code {
			case "workbuddy_service_unavailable", "workbuddy_identity_rejected", "workbuddy_enrollment_rejected", "workbuddy_session_expired":
				code = service.Code
			}
		}
		var deadline *WorkBuddyEnrollmentDeadline
		if errors.As(err, &deadline) {
			reason = "managed session enrollment deadline during request"
			code = "workbuddy_enrollment_deadline_during_request"
			if deadline.BeforeRequest {
				reason = "managed session enrollment deadline before request"
				code = "workbuddy_enrollment_deadline_before_request"
			}
		}
		return fail("enrollment", code, reason)
	}
	dec, err := d.Decide(req)
	var failure *WorkBuddyManagedFailure
	if errors.As(err, &failure) {
		reason := "managed approval or correlation unavailable"
		code := "workbuddy_correlation_unavailable"
		switch failure.Code {
		case "workbuddy_correlation_lock_unavailable", "workbuddy_correlation_history_unavailable", "workbuddy_correlation_pre_unavailable":
			code = failure.Code
		}
		if failure.Uncertain {
			reason = "execution uncertain; inspect SIQ and do not replay"
			code = "workbuddy_execution_uncertain"
		}
		return fail("correlation", code, reason)
	}
	if err != nil || dec == nil || dec.Receipt.ReceiptID == "" || dec.Receipt.ActionID == "" {
		return fail("decision", "workbuddy_decision_unavailable", "managed decision unavailable")
	}
	switch dec.Action {
	case receipt.ActionAllow:
		// Omitting permissionDecision lets WorkBuddy apply its own permission gate.
		return out
	case receipt.ActionDeny:
		out.HookSpecificOutput.PermissionDecision = "deny"
		out.HookSpecificOutput.PermissionDecisionReason = product.Name + ": " + dec.Reason + " (receipt " + dec.Receipt.ReceiptID + ")"
	case receipt.ActionHold:
		out.HookSpecificOutput.PermissionDecision = "deny"
		out.HookSpecificOutput.PermissionDecisionReason = product.Name + ": approval required; approve in SIQ and retry the same action in WorkBuddy (receipt " + dec.Receipt.ReceiptID + ")"
	case receipt.ActionRedact:
		out.HookSpecificOutput.PermissionDecision = "deny"
		out.HookSpecificOutput.PermissionDecisionReason = product.Name + ": parameter rewrite is not supported (receipt " + dec.Receipt.ReceiptID + ")"
	default:
		return fail("decision", "workbuddy_decision_invalid", "invalid managed decision")
	}
	return out
}

func WorkBuddyManagedDeny(tool, session, mode, stateDir, reason string) WorkBuddyOutput {
	var out WorkBuddyOutput
	out.HookSpecificOutput.HookEventName = "PreToolUse"
	out.HookSpecificOutput.PermissionDecision = "deny"
	out.HookSpecificOutput.PermissionDecisionReason = product.Name + ": " + reason + "; blocked (fail-closed)"
	_ = pending.Append(stateDir, pending.Record{Platform: "workbuddy", Tool: tool, SessionID: session, EnforcementMode: mode, Outcome: "deny", Reason: reason})
	return out
}
