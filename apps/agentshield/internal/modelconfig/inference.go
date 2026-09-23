package modelconfig

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"
)

// Infer submits one fixed public connection test, never a user or business prompt.
// A transport error is uncertain: the remote service may already have accepted it.
func Infer(ctx context.Context, t Target) string {
	u, err := endpoint(t.URL)
	if err != nil || !t.Item.CanCheck {
		return "configuration_changed"
	}
	nonce := make([]byte, 12)
	if _, err := rand.Read(nonce); err != nil {
		return "service_error"
	}
	expected := "SIQ_MODEL_TEST_" + hex.EncodeToString(nonce)
	payload, _ := json.Marshal(map[string]any{"model": t.Item.Model, "messages": []map[string]string{{"role": "user", "content": "This is a connection test. Reply with exactly " + expected + " and no other text."}}, "stream": false, "max_tokens": 512})
	u.Path = strings.TrimRight(u.Path, "/") + "/chat/completions"
	if u.RawPath != "" {
		u.RawPath = strings.TrimRight(u.RawPath, "/") + "/chat/completions"
	}
	ctx, cancel := context.WithTimeout(ctx, 45*time.Second)
	defer cancel()
	transport := modelTransport(u)
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, u.String(), bytes.NewReader(payload))
	if err != nil {
		return "configuration_changed"
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	if t.Key != "" {
		req.Header.Set("Authorization", "Bearer "+t.Key)
	}
	response, err := client.Do(req)
	if err != nil {
		return "uncertain"
	}
	defer response.Body.Close()
	switch {
	case response.StatusCode == 401 || response.StatusCode == 403:
		return "auth_failed"
	case response.StatusCode == 429:
		return "rate_limited"
	case response.StatusCode == 400 || response.StatusCode == 404 || response.StatusCode == 405 || response.StatusCode >= 300 && response.StatusCode < 400:
		return "unsupported_response"
	case response.StatusCode != 200:
		return "service_error"
	}
	if !strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		return "unsupported_response"
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, (1<<20)+1))
	if err != nil {
		return "uncertain"
	}
	if len(raw) > 1<<20 || !uniqueJSON(raw) {
		return "unsupported_response"
	}
	return validateInference(raw, t.Item.Model, expected)
}

func validateInference(raw []byte, model, expected string) string {
	var doc struct {
		Model   string `json:"model"`
		Choices []struct {
			Finish  string `json:"finish_reason"`
			Message struct {
				Role     string          `json:"role"`
				Content  string          `json:"content"`
				Tools    json.RawMessage `json:"tool_calls"`
				Function json.RawMessage `json:"function_call"`
			} `json:"message"`
		} `json:"choices"`
	}
	if !uniqueJSON(raw) || json.Unmarshal(raw, &doc) != nil || len(doc.Choices) != 1 {
		return "unsupported_response"
	}
	choice := doc.Choices[0]
	absent := func(value json.RawMessage) bool {
		v := strings.TrimSpace(string(value))
		return v == "" || v == "null" || v == "[]"
	}
	if doc.Model != model || choice.Finish != "stop" || choice.Message.Role != "assistant" || strings.TrimSpace(choice.Message.Content) != expected || !absent(choice.Message.Tools) || !absent(choice.Message.Function) {
		return "response_mismatch"
	}
	return "passed"
}
