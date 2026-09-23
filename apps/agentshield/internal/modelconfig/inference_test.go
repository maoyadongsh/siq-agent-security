package modelconfig

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func TestInferExactPublicPromptAndResponse(t *testing.T) {
	var calls atomic.Int32
	service := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.Method != "POST" || r.URL.Path != "/v1/chat/completions" || r.Header.Get("Authorization") != "Bearer synthetic-key" {
			t.Error("wrong request destination or authorization")
		}
		var body map[string]json.RawMessage
		if json.NewDecoder(r.Body).Decode(&body) != nil || len(body) != 4 || string(body["max_tokens"]) != "512" || string(body["stream"]) != "false" || string(body["model"]) != `"fixture-model"` {
			t.Error("test request must contain only the bounded fixed completion")
		}
		var messages []struct{ Role, Content string }
		if json.Unmarshal(body["messages"], &messages) != nil || len(messages) != 1 || messages[0].Role != "user" {
			t.Error("unexpected messages")
			w.WriteHeader(400)
			return
		}
		marker := strings.TrimSuffix(strings.TrimPrefix(messages[0].Content, "This is a connection test. Reply with exactly "), " and no other text.")
		if !strings.HasPrefix(marker, "SIQ_MODEL_TEST_") || len(marker) != len("SIQ_MODEL_TEST_")+24 {
			t.Error("missing random public marker")
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"model": "fixture-model", "choices": []any{map[string]any{"finish_reason": "stop", "message": map[string]any{"role": "assistant", "content": marker}}}})
	}))
	defer service.Close()
	target := Discover(sourceFixture(t, "hermes", "model:\n  default: fixture-model\n  provider: custom:fixture\n  api_mode: openai_chat\n  base_url: "+service.URL+"/v1\n  api_key: synthetic-key\n"))[0]
	if status := Infer(context.Background(), target); status != "passed" || calls.Load() != 1 {
		t.Fatalf("status=%s calls=%d", status, calls.Load())
	}
}

func TestInferRejectsFalseSuccess(t *testing.T) {
	valid := `{"model":"fixture-model","choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"SIQ_MODEL_TEST_expected"}}]}`
	for _, tc := range []struct{ name, raw, want string }{
		{"valid", valid, "passed"},
		{"different-model", strings.Replace(valid, "fixture-model", "fallback-model", 1), "response_mismatch"},
		{"unfinished", strings.Replace(valid, `"stop"`, `"length"`, 1), "response_mismatch"},
		{"wrong-answer", strings.Replace(valid, "SIQ_MODEL_TEST_expected", "SUCCESS", 1), "response_mismatch"},
		{"wrong-role", strings.Replace(valid, `"assistant"`, `"user"`, 1), "response_mismatch"},
		{"tool-call", strings.Replace(valid, `"role":"assistant"`, `"role":"assistant","tool_calls":[{"id":"call-1"}]`, 1), "response_mismatch"},
		{"function-call", strings.Replace(valid, `"role":"assistant"`, `"role":"assistant","function_call":{"name":"tool"}`, 1), "response_mismatch"},
		{"duplicate-field", strings.Replace(valid, `"model":`, `"model":"another","model":`, 1), "unsupported_response"},
		{"no-choice", `{"model":"fixture-model","choices":[]}`, "unsupported_response"},
		{"malformed", valid + `{}`, "unsupported_response"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := validateInference([]byte(tc.raw), "fixture-model", "SIQ_MODEL_TEST_expected"); got != tc.want {
				t.Fatalf("got %s want %s", got, tc.want)
			}
		})
	}
}

func TestInferFailuresDoNotRetryOrFollowRedirects(t *testing.T) {
	var forwarded atomic.Int32
	destination := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { forwarded.Add(1) }))
	defer destination.Close()
	for _, tc := range []struct {
		code int
		want string
	}{{401, "auth_failed"}, {403, "auth_failed"}, {429, "rate_limited"}, {503, "service_error"}, {400, "unsupported_response"}, {404, "unsupported_response"}, {307, "unsupported_response"}} {
		t.Run(http.StatusText(tc.code), func(t *testing.T) {
			var calls atomic.Int32
			service := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				w.Header().Set("Location", destination.URL)
				w.WriteHeader(tc.code)
				_, _ = w.Write([]byte("synthetic-private-response"))
			}))
			defer service.Close()
			target := Discover(sourceFixture(t, "hermes", "model:\n  default: fixture-model\n  provider: custom:fixture\n  api_mode: openai_chat\n  base_url: "+service.URL+"\n"))[0]
			if got := Infer(context.Background(), target); got != tc.want || calls.Load() != 1 {
				t.Fatalf("got %s calls=%d", got, calls.Load())
			}
		})
	}
	if forwarded.Load() != 0 {
		t.Fatal("followed redirect")
	}
	for _, tc := range []struct {
		name, contentType, body string
		want                    string
	}{
		{"html", "text/html", "synthetic-private-response", "unsupported_response"},
		{"oversize", "application/json", strings.Repeat(" ", 1<<20) + "{}", "unsupported_response"},
		{"invalid-json", "application/json", "PRIVATE-NOT-JSON", "unsupported_response"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			service := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", tc.contentType)
				_, _ = w.Write([]byte(tc.body))
			}))
			defer service.Close()
			target := Discover(sourceFixture(t, "hermes", "model:\n  default: fixture-model\n  provider: custom:fixture\n  api_mode: openai_chat\n  base_url: "+service.URL+"\n"))[0]
			if got := Infer(context.Background(), target); got != tc.want {
				t.Fatalf("got %s", got)
			}
		})
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	target := Discover(sourceFixture(t, "hermes", "model:\n  default: fixture-model\n  provider: custom:fixture\n  api_mode: openai_chat\n  base_url: "+destination.URL+"\n"))[0]
	if got := Infer(ctx, target); got != "uncertain" || forwarded.Load() != 0 {
		t.Fatalf("cancelled call: %s", got)
	}
}
