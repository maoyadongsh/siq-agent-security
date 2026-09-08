package server

import "testing"

func TestProvenanceReportsRejectRevokedAuthorityAcrossRestart(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		for _, kind := range []string{"binding", "intent"} {
			t.Run(mode+"/"+kind, func(t *testing.T) {
				s, _ := newServer(t, mode)
				issued := effectCall(t, s, "POST", "/v1/intents", s.bootAdmin, apiIntent(), 201)
				binding := effectCall(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, map[string]any{"platform": "hermes", "session_id": "s1", "agent_id": "a-1", "intent_id": "int-api"}, 201)
				report := map[string]any{"report_id": "before-revoke", "platform": "hermes", "session_id": "s1", "agent_id": "a-1", "source": map[string]any{"type": "MCP", "source_id": "server/tool"}, "content": map[string]any{"recipient": "fixture@example.test"}}
				parent := effectCall(t, s, "POST", "/v1/provenance-reports", token, report, 201)
				selection := map[string]any{"parent_id": parent["provenance_id"], "pointer": "/recipient", "platform": "hermes", "session_id": "s1", "agent_id": "a-1", "content": report["content"]}
				effectCall(t, s, "POST", "/v1/provenance-select", token, selection, 201)
				path := "/v1/intents/int-api/revoke"
				if kind == "binding" {
					path = "/v1/intent-bindings/" + binding["binding_id"].(string) + "/revoke"
				}
				effectCall(t, s, "POST", path, s.bootAdmin, map[string]any{"expected_intent_digest": issued["digest"]}, 200)
				for _, restart := range []bool{false, true} {
					if restart {
						var err error
						s, err = New(s.d)
						if err != nil {
							t.Fatal(err)
						}
					}
					// Both replay and fresh issuance must recheck current authority.
					for _, id := range []string{"before-revoke", "after-revoke"} {
						report["report_id"] = id
						out := effectCall(t, s, "POST", "/v1/provenance-reports", token, report, 400)
						if out["reason_code"] != "provenance_authority_invalid" {
							t.Fatal("revoked report authority", restart, out)
						}
					}
					out := effectCall(t, s, "POST", "/v1/provenance-select", token, selection, 400)
					if out["reason_code"] != "provenance_authority_invalid" {
						t.Fatal("revoked selection authority", restart, out)
					}
				}
			})
		}
	}
}

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
	selection := map[string]any{"parent_id": out["provenance_id"], "pointer": "/recipient", "platform": "hermes", "session_id": "s1", "agent_id": "a-1", "content": body["content"]}
	status, child := call(t, s, "POST", "/v1/provenance-select", token, selection)
	if status != 201 || child["derivation"] != "transformed" {
		t.Fatal("selection failed", status, child)
	}
	selection["value"] = "attacker@example.test"
	status, _ = call(t, s, "POST", "/v1/provenance-select", token, selection)
	if status != 400 {
		t.Fatal("caller supplied selected output", status)
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
