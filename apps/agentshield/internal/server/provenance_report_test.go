package server

import "testing"

func TestDecisionReportCannotMintTrustedAuthority(t *testing.T) {
	s, _ := newServer(t, "block")
	status, _ := call(t, s, "POST", "/v1/intents", s.bootAdmin, apiIntent())
	if status != 201 {
		t.Fatal(status)
	}
	status, _ = call(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, map[string]any{"platform": "hermes", "session_id": "s1", "agent_id": "a-1", "intent_id": "int-api"})
	if status != 201 {
		t.Fatal(status)
	}
	body := map[string]any{"report_id": "report-http", "platform": "hermes", "session_id": "s1", "agent_id": "a-1", "source": map[string]any{"type": "MCP", "source_id": "server/tool"}, "content": map[string]any{"recipient": "fixture@example.test"}}
	status, out := call(t, s, "POST", "/v1/provenance-reports", token, body)
	if status != 201 || out["source"].(map[string]any)["trust"] != "untrusted" {
		t.Fatal(status, out)
	}
	status, _ = call(t, s, "POST", "/v1/provenance-reports", s.bootAdmin, body)
	if status != 401 {
		t.Fatal("admin session confused with decision credential", status)
	}
	for _, field := range []string{"issuer", "task_id", "signature"} {
		body[field] = "forged"
		status, _ = call(t, s, "POST", "/v1/provenance-reports", token, body)
		if status != 400 {
			t.Fatal("caller supplied authority", field, status)
		}
		delete(body, field)
	}
	body["source"] = map[string]any{"type": "USER", "source_id": "caller", "trust": "authoritative"}
	status, _ = call(t, s, "POST", "/v1/provenance-reports", token, body)
	if status != 400 {
		t.Fatal("USER authority forgery", status)
	}
	body["source"] = map[string]any{"type": "MCP", "source_id": "caller"}
	body["session_id"] = "unbound"
	status, _ = call(t, s, "POST", "/v1/provenance-reports", token, body)
	if status != 400 {
		t.Fatal("report invented task authority", status)
	}
}
