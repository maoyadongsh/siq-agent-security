package server

import (
	"strings"
	"testing"
)

func TestGlobalIntentRevocationManagementHTTP(t *testing.T) {
	s, _ := newServer(t, "block")
	issued := effectCall(t, s, "POST", "/v1/intents", s.bootAdmin, apiIntent(), 201)
	path := "/v1/intents/int-api"
	body := map[string]any{"expected_intent_digest": issued["digest"]}
	effectCall(t, s, "POST", path+"/revoke", token, body, 403)
	effectCall(t, s, "GET", path+"/revocation", token, nil, 403)
	effectCall(t, s, "GET", path+"/revocation", s.bootAdmin, nil, 404)
	effectCall(t, s, "POST", path+"/revoke", s.bootAdmin, map[string]any{"expected_intent_digest": strings.Repeat("f", 64)}, 409)
	effectCall(t, s, "POST", path+"/revoke", s.bootAdmin, map[string]any{"expected_intent_digest": issued["digest"], "reason": "caller-input"}, 400)
	revoked := effectCall(t, s, "POST", path+"/revoke", s.bootAdmin, body, 200)
	retry := effectCall(t, s, "POST", path+"/revoke", s.bootAdmin, body, 200)
	read := effectCall(t, s, "GET", path+"/revocation", s.bootAdmin, nil, 200)
	if revoked["signature"] != retry["signature"] || revoked["signature"] != read["signature"] || revoked["reason_code"] != "intent_revoked" {
		t.Fatal("revocation changed", revoked)
	}
	historical := effectCall(t, s, "GET", path, s.bootAdmin, nil, 200)
	if historical["signature"] != issued["signature"] {
		t.Fatal("historical intent rewritten")
	}
	effectCall(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, map[string]any{"platform": "hermes", "session_id": "after-revoke", "agent_id": "a-1", "intent_id": "int-api"}, 400)
}
