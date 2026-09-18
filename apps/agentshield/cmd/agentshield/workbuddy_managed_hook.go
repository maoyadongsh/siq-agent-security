package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

type workBuddyManagedClient struct {
	config adapters.WorkBuddyManagedConfig
	token  string
	client *http.Client
	ctx    context.Context
}

func (h *workBuddyManagedClient) post(path string, body any) ([]byte, error) {
	return h.postStatus(path, body, http.StatusOK)
}

func (h *workBuddyManagedClient) postStatus(path string, body any, expected int) ([]byte, error) {
	raw, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(h.ctx, http.MethodPost, h.config.Endpoint+path, bytes.NewReader(raw))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+h.token)
	req.Header.Set("Content-Type", "application/json")
	resp, err := h.client.Do(req)
	if err != nil {
		return nil, errors.New("managed service unavailable")
	}
	defer resp.Body.Close()
	if resp.StatusCode != expected {
		return nil, errors.New("managed service rejected request")
	}
	raw, err = io.ReadAll(io.LimitReader(resp.Body, adapters.WorkBuddyHookLimit+1))
	if err != nil || len(raw) > adapters.WorkBuddyHookLimit {
		return nil, errors.New("managed response invalid")
	}
	return raw, nil
}

func (h *workBuddyManagedClient) Enroll(session string) error {
	if h.ctx.Err() != nil {
		return &adapters.WorkBuddyEnrollmentDeadline{BeforeRequest: true}
	}
	raw, err := h.post("/v1/runtime-sessions", map[string]string{"schema_version": "local-runtime-session-enroll/v1", "session_id": session})
	if err != nil {
		if h.ctx.Err() != nil {
			return &adapters.WorkBuddyEnrollmentDeadline{}
		}
		return err
	}
	var out struct {
		SchemaVersion string `json:"schema_version"`
		IdentityID    string `json:"identity_id"`
		Platform      string `json:"platform"`
		AgentID       string `json:"agent_id"`
		SessionID     string `json:"session_id"`
		BindingID     string `json:"binding_id"`
		IntentID      string `json:"intent_id"`
		ExpiresAt     string `json:"expires_at"`
	}
	fields := []string{"schema_version", "identity_id", "platform", "agent_id", "session_id", "binding_id", "intent_id", "expires_at"}
	if adapters.DecodeWorkBuddyObject(raw, fields, fields, &out) != nil || out.SchemaVersion != "local-runtime-session-enrolled/v2" ||
		out.IdentityID != h.config.RuntimeIdentityID || out.Platform != "workbuddy" || out.AgentID != h.config.AgentID || out.SessionID != session || out.BindingID == "" || out.IntentID == "" {
		return errors.New("managed enrollment response mismatch")
	}
	expires, err := time.Parse(time.RFC3339Nano, out.ExpiresAt)
	if err != nil || !expires.After(time.Now()) {
		return errors.New("managed enrollment expired")
	}
	return nil
}

func (h *workBuddyManagedClient) requestDecision(req receipt.Request) (*receipt.Decision, error) {
	raw, err := h.post("/v1/decide", req)
	if err != nil {
		return nil, err
	}
	var out map[string]json.RawMessage
	allowed := []string{"action", "reason", "receipt_id", "action_id", "reason_code", "task_id", "runtime_task_id", "authority_status", "effective_action", "trifecta", "authority_reason_code", "skill_attribution", "policy_action", "params", "hold"}
	if adapters.DecodeWorkBuddyObject(raw, []string{"action", "reason", "receipt_id", "action_id", "authority_status", "effective_action"}, allowed, &out) != nil {
		return nil, errors.New("managed decision invalid")
	}
	var d receipt.Decision
	for name, dest := range map[string]*string{"action": &d.Action, "reason": &d.Reason, "receipt_id": &d.Receipt.ReceiptID, "action_id": &d.Receipt.ActionID, "authority_status": &d.Receipt.AuthorityStatus, "effective_action": &d.Receipt.EffectiveAction} {
		if json.Unmarshal(out[name], dest) != nil || bytes.Equal(out[name], []byte("null")) {
			return nil, errors.New("managed decision invalid")
		}
	}
	if d.Action == receipt.ActionAllow && (d.Receipt.AuthorityStatus != "valid" || d.Receipt.EffectiveAction != receipt.ActionAllow) {
		return nil, errors.New("managed authority response mismatch")
	}
	if p, ok := out["params"]; ok && json.Unmarshal(p, &d.Params) != nil {
		return nil, errors.New("managed decision invalid")
	}
	for name, dest := range map[string]*string{"task_id": &d.Receipt.TaskID, "runtime_task_id": &d.Receipt.RuntimeTaskID} {
		if value, ok := out[name]; ok && (json.Unmarshal(value, dest) != nil || bytes.Equal(bytes.TrimSpace(value), []byte("null"))) {
			return nil, errors.New("managed task response invalid")
		}
	}
	if d.Action == receipt.ActionHold {
		if d.Receipt.AuthorityStatus != "valid" || d.Receipt.EffectiveAction != receipt.ActionHold || json.Unmarshal(out["hold"], &d.Hold) != nil || d.Hold == nil || d.Hold.TimeoutMS <= 0 {
			return nil, errors.New("managed hold response invalid")
		}
	}
	return &d, nil
}

func (h *workBuddyManagedClient) requestObservation(req receipt.Request, result string) error {
	body := map[string]any{"platform": req.Platform, "session_id": req.SessionID, "agent_id": req.AgentID, "tool": req.Tool, "tool_call_id": req.ToolCallID, "params": req.Params, "result": result, "action_id": req.ActionID, "decision_receipt_id": req.DecisionReceiptID, "task_id": req.TaskID, "runtime_task_id": req.RuntimeTaskID}
	raw, err := h.post("/v1/observe", body)
	if err != nil {
		return err
	}
	var out struct {
		ReceiptID   string   `json:"receipt_id"`
		ActionID    string   `json:"action_id"`
		TaintLabels []string `json:"taint_labels"`
	}
	fields := []string{"receipt_id", "action_id", "taint_labels"}
	if adapters.DecodeWorkBuddyObject(raw, fields, fields, &out) != nil || out.ReceiptID == "" || out.ActionID == "" || out.ActionID != req.ActionID {
		return errors.New("managed observation invalid")
	}
	return nil
}

func runWorkBuddySelectedHook(configPath string, explicit bool, in io.Reader, out io.Writer) error {
	dir, err := stateDir()
	if err != nil {
		return json.NewEncoder(out).Encode(adapters.WorkBuddyManagedDeny("", "", "block", "", "managed state unavailable"))
	}
	if !explicit {
		home, homeErr := os.UserHomeDir()
		if homeErr != nil {
			return json.NewEncoder(out).Encode(adapters.WorkBuddyManagedDeny("", "", "block", dir, "managed configuration unavailable"))
		}
		var managed bool
		configPath, managed, err = adapterinstall.WorkBuddyManagedConfigReference(home, dir)
		if err != nil {
			return json.NewEncoder(out).Encode(adapters.WorkBuddyManagedDeny("", "", "block", dir, "managed configuration unavailable"))
		}
		if !managed {
			d, mode, state := hostHookClient()
			return writeHostHook("workbuddy", in, out, d, mode, state)
		}
	}
	return runWorkBuddyManagedHook(configPath, dir, in, out)
}

func runWorkBuddyManagedHook(configPath, dir string, in io.Reader, out io.Writer) error {
	return runWorkBuddyManagedHookWithBudget(configPath, dir, in, out, 60*time.Second)
}

func runWorkBuddyManagedHookWithBudget(configPath, dir string, in io.Reader, out io.Writer, budget time.Duration) error {
	if !filepath.IsAbs(configPath) || filepath.Clean(configPath) != configPath || filepath.Base(configPath) != "siq-agent-security.json" {
		return json.NewEncoder(out).Encode(adapters.WorkBuddyManagedHook(in, nil, "", "block", dir))
	}
	// Reading configuration is not allowed to initialize state, mint credentials,
	// consult daily host databases, or fall back to the shared decision token.
	raw, err := statefs.ReadPrivateFile(configPath, 16<<10)
	cfg, cfgErr := adapters.DecodeWorkBuddyManagedConfig(raw, configPath, dir)
	if runtime.GOOS != "windows" || err != nil || cfgErr != nil {
		return json.NewEncoder(out).Encode(adapters.WorkBuddyManagedHook(in, nil, "", "block", dir))
	}
	raw, err = statefs.ReadPrivateFile(cfg.CredentialPath, 4096)
	token := strings.TrimSpace(string(raw))
	if err != nil || len(token) < 32 || len(token) > 4096 || strings.ContainsAny(token, " \t\r\n") {
		return json.NewEncoder(out).Encode(adapters.WorkBuddyManagedHook(in, nil, "", cfg.EnforcementMode, dir))
	}
	// One deadline bounds enroll + decide together; retries do not renew the Windows I/O budget.
	ctx, cancel := context.WithTimeout(context.Background(), budget)
	defer cancel()
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	defer transport.CloseIdleConnections()
	client := &http.Client{Timeout: budget, Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	d := &workBuddyManagedClient{config: cfg, token: token, client: client, ctx: ctx}
	return json.NewEncoder(out).Encode(adapters.WorkBuddyManagedHook(in, d, cfg.AgentID, cfg.EnforcementMode, dir))
}
