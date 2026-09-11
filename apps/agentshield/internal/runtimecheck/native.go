package runtimecheck

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
)

type probeCall struct {
	id, tool string
	params   map[string]any
}
type probeModel struct {
	mu       sync.Mutex
	prefix   string
	proof    string
	calls    []probeCall
	step     int
	requests int
	complete bool
	failed   bool
}

func (m *Manager) launch(ctx context.Context, r *run, target adapterinstall.RuntimeTarget, nonce string, p probes) error {
	if ctx.Err() != nil {
		return errors.New("runtime_check_cancelled")
	}
	current, err := m.snapshot(target.InstanceID)
	if err != nil || current.Digest != target.Digest {
		return errors.New("runtime_check_snapshot_changed")
	}
	modelID, err := randomHex(24)
	if err != nil {
		return err
	}
	model := &probeModel{prefix: "/" + modelID + "/v1", proof: p.proof, calls: []probeCall{
		{"rc-first", "read_file", map[string]any{"path": p.first}},
		{"rc-denied", "write_file", map[string]any{"path": p.forbidden, "content": "SIQ negative probe must not execute"}},
		{"rc-last", "read_file", map[string]any{"path": p.last}},
	}}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return errors.New("runtime_check_model_unavailable")
	}
	server := &http.Server{Handler: model, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 10 * time.Second, IdleTimeout: 10 * time.Second, MaxHeaderBytes: 16 << 10}
	finished := make(chan struct{})
	go func() { defer close(finished); _ = server.Serve(listener) }()
	defer func() { _ = server.Close(); <-finished }()
	env := []string{}
	for _, key := range []string{"PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"} {
		if value := os.Getenv(key); value != "" {
			env = append(env, key+"="+value)
		}
	}
	env = append(env, "HOME="+target.Home, "USERPROFILE="+target.Home, "HERMES_HOME="+target.ProfilePath,
		"SIQ_AGENT_SECURITY_STATE_DIR="+m.o.Store.Dir, "AGENTSHIELD_STATE_DIR="+m.o.Store.Dir,
		"SIQ_AGENT_SECURITY_AGENT_ID="+agentID(r.id), "SIQ_RUNTIME_CHECK_ID="+r.id,
		"SIQ_RUNTIME_CHECK_INSTANCE="+target.InstanceID, "SIQ_RUNTIME_CHECK_TOKEN="+nonce,
		"CUSTOM_BASE_URL=http://"+listener.Addr().String()+model.prefix, "NO_PROXY=127.0.0.1,localhost,::1",
		"PYTHONDONTWRITEBYTECODE=1", "PYTHONNOUSERSITE=1", "HERMES_ENABLE_PROJECT_PLUGINS=0", "NO_COLOR=1")
	if value := os.Getenv("LOCALAPPDATA"); value != "" {
		env = append(env, "LOCALAPPDATA="+value)
	}
	command := exec.CommandContext(ctx, target.NativeCLI, "chat", "--provider", "custom", "--model", "siq-synthetic-fixture", "--toolsets", "file", "--max-turns", "6", "--run-budget", "45", "--ignore-rules", "--quiet", "--oneshot", "-q", "Execute the SIQ synthetic runtime check.")
	command.Dir, command.Env, command.WaitDelay = p.dir, env, 2*time.Second
	// Nil streams connect to the null device; host output and model request
	// contents are never persisted or included in public failure messages.
	err = command.Run()
	model.mu.Lock()
	defer model.mu.Unlock()
	if err != nil {
		return errors.New("runtime_check_host_failed")
	}
	if !model.complete || model.failed {
		return errors.New("runtime_check_probe_incomplete")
	}
	return nil
}

func (p *probeModel) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if r.URL.RawQuery != "" || !strings.HasPrefix(r.URL.Path, p.prefix+"/") {
		w.WriteHeader(404)
		return
	}
	p.requests++
	if p.requests > 32 {
		p.failed = true
		w.WriteHeader(429)
		return
	}
	if r.Method == http.MethodGet && r.URL.Path == p.prefix+"/models" {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"object": "list", "data": []any{map[string]any{"id": "siq-synthetic-fixture", "object": "model", "owned_by": "siq", "created": 0}}})
		return
	}
	if r.Method != http.MethodPost || r.URL.Path != p.prefix+"/chat/completions" {
		w.WriteHeader(404)
		return
	}
	var body struct {
		Model    string `json:"model"`
		Stream   bool   `json:"stream"`
		Messages []struct {
			Role       string `json:"role"`
			Content    any    `json:"content"`
			ToolCallID string `json:"tool_call_id"`
		} `json:"messages"`
		Tools []struct {
			Function struct {
				Name string `json:"name"`
			} `json:"function"`
		} `json:"tools"`
	}
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20))
	decoder.UseNumber()
	var extra any
	if decoder.Decode(&body) != nil || decoder.Decode(&extra) != io.EOF || body.Model != "siq-synthetic-fixture" {
		p.failed = true
		w.WriteHeader(400)
		return
	}
	main := false
	for _, tool := range body.Tools {
		if tool.Function.Name == "read_file" {
			main = true
		}
	}
	if !main {
		p.respond(w, body.Stream, map[string]any{"role": "assistant", "content": "SIQ check"}, "stop")
		return
	}
	results := []struct{ ID, Content string }{}
	for _, message := range body.Messages {
		if message.Role == "tool" {
			results = append(results, struct{ ID, Content string }{message.ToolCallID, fmt.Sprint(message.Content)})
		}
	}
	if p.step > len(p.calls) || len(results) != p.step {
		p.failed = true
		w.WriteHeader(409)
		return
	}
	for i, result := range results {
		if result.ID != p.calls[i].id || (i != 1 && !strings.Contains(result.Content, p.proof)) || (i == 1 && !strings.Contains(result.Content, "siq-agent-security")) {
			p.failed = true
			w.WriteHeader(409)
			return
		}
	}
	if p.step == len(p.calls) {
		p.complete = true
		p.respond(w, body.Stream, map[string]any{"role": "assistant", "content": "SIQ_RUNTIME_CHECK_COMPLETE"}, "stop")
		p.step++
		return
	}
	call := p.calls[p.step]
	p.step++
	arguments, _ := json.Marshal(call.params)
	p.respond(w, body.Stream, map[string]any{"role": "assistant", "content": nil, "tool_calls": []any{map[string]any{"index": 0, "id": call.id, "type": "function", "function": map[string]any{"name": call.tool, "arguments": string(arguments)}}}}, "tool_calls")
}
func (p *probeModel) respond(w http.ResponseWriter, stream bool, message map[string]any, finish string) {
	base := map[string]any{"id": "siq-runtime-check", "created": 0, "model": "siq-synthetic-fixture"}
	if !stream {
		w.Header().Set("Content-Type", "application/json")
		base["object"] = "chat.completion"
		base["choices"] = []any{map[string]any{"index": 0, "message": message, "finish_reason": finish}}
		base["usage"] = map[string]any{"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
		_ = json.NewEncoder(w).Encode(base)
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-store")
	base["object"] = "chat.completion.chunk"
	for i, delta := range []map[string]any{message, {}} {
		var why any
		if i == 1 {
			why = finish
		}
		base["choices"] = []any{map[string]any{"index": 0, "delta": delta, "finish_reason": why}}
		raw, _ := json.Marshal(base)
		_, _ = fmt.Fprintf(w, "data: %s\n\n", raw)
	}
	_, _ = fmt.Fprint(w, "data: [DONE]\n\n")
	if flusher, ok := w.(http.Flusher); ok {
		flusher.Flush()
	}
}
