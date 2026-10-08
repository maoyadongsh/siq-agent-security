package server

import (
	"encoding/json"
	"io"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestDecisionPathsRejectOversizedBodiesBeforeMutation(t *testing.T) {
	s, _ := newServer(t, "block")
	beforeSeq, beforeHash := s.d.Chain.Head()
	oversized := `{"platform":"hermes","session_id":"limit-session","tool":"read","params":{"note":"` + strings.Repeat("a", 4<<20) + `"}}`
	code, body := rawDecisionCall(t, s, "POST", "/v1/decide", token, oversized)
	if code != 413 || body["error"] != "decision_request_too_large" {
		t.Fatalf("oversized decide status=%d body=%v", code, body)
	}
	code, body = rawDecisionCall(t, s, "POST", "/v1/observe", token, oversized)
	if code != 413 || body["error"] != "decision_request_too_large" {
		t.Fatalf("oversized observe status=%d body=%v", code, body)
	}
	malformed := `{"platform":`
	code, body = rawDecisionCall(t, s, "POST", "/v1/decide", token, malformed)
	if code != 400 {
		t.Fatalf("malformed decide status=%d body=%v", code, body)
	}
	holdBody := `{"approve":true,"actor_id":"` + strings.Repeat("h", 70<<10) + `"}`
	code, body = rawDecisionCall(t, s, "POST", "/v1/hold/missing-receipt", s.bootAdmin, holdBody)
	if code != 413 {
		t.Fatalf("oversized hold status=%d body=%v", code, body)
	}
	afterSeq, afterHash := s.d.Chain.Head()
	if afterSeq != beforeSeq || afterHash != beforeHash {
		t.Fatalf("oversized request changed chain %d/%s -> %d/%s", beforeSeq, beforeHash, afterSeq, afterHash)
	}
}

func rawDecisionCall(t *testing.T, s *Server, method, path, tok, body string) (int, map[string]any) {
	t.Helper()
	req := loopbackRequest(method, path, nil)
	req.Body = io.NopCloser(strings.NewReader(body))
	req.ContentLength = int64(len(body))
	req.Header.Set("Authorization", "Bearer "+tok)
	response := httptest.NewRecorder()
	s.Handler().ServeHTTP(response, req)
	var out map[string]any
	_ = json.Unmarshal(response.Body.Bytes(), &out)
	return response.Code, out
}
