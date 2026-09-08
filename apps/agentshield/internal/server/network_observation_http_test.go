package server

import (
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/url"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/completion"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

func TestNetworkObservationHTTPActualReceiptAndCapability(t *testing.T) {
	s, st := newServer(t, "block")
	eng, err := receipt.New(receipt.Options{Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant, EnforcementMode: "block", IntentLookup: receipt.ResolveStore(s.intents)})
	if err != nil {
		t.Fatal(err)
	}
	s.d.Engine = eng
	effectCall(t, s, "POST", "/v1/intents", s.bootAdmin, apiIntent(), 201)
	effectCall(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, map[string]any{"platform": "hermes", "session_id": "s1", "agent_id": "a-1", "intent_id": "int-api"}, 201)
	oracle, err := effectevidence.NewNetworkOracle("127.0.0.1")
	if err != nil {
		t.Fatal(err)
	}
	defer oracle.Close()
	d, err := eng.Decide(receipt.Request{Platform: "hermes", SessionID: "s1", AgentID: "a-1", Tool: "web_fetch", ToolCallID: "network-call", Params: map[string]any{"url": oracle.URL()}})
	if err != nil || d.Action != "deny" {
		t.Fatal(d, err)
	}
	if _, err := oracle.Material(0, oracle.URL()); err == nil {
		t.Fatal("fabricated event before receipt")
	}
	client := &http.Client{Timeout: 3 * time.Second}
	response, err := client.Post(oracle.URL(), "text/plain", strings.NewReader("synthetic-private-body"))
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 204 {
		t.Fatal(response.StatusCode)
	}
	material, err := oracle.Material(0, oracle.URL())
	if err != nil {
		t.Fatal(err)
	}
	provision := map[string]any{"source": oracle.Source(), "scope": provenance.Scope{Platform: "hermes", SessionID: "s1", AgentID: "a-1", TaskID: "task-1"}, "expires_in": 60}
	issued := effectCall(t, s, "POST", "/v1/effect-observers", s.bootAdmin, provision, 201)
	observer := issued["token"].(string)
	body := map[string]any{"observation_id": "network-http", "action_id": d.Receipt.ActionID, "decision_receipt_id": d.Receipt.ReceiptID, "observation": material}
	for _, tok := range []string{token, s.bootAdmin} {
		effectCall(t, s, "POST", "/v1/network-observations", tok, body, 403)
	}
	effectCall(t, s, "GET", "/v1/network-observations", observer, nil, 405)
	body["source"] = oracle.Source()
	effectCall(t, s, "POST", "/v1/network-observations", observer, body, 400)
	delete(body, "source")
	body["decision_receipt_id"] = "forged"
	effectCall(t, s, "POST", "/v1/network-observations", observer, body, 400)
	body["decision_receipt_id"] = d.Receipt.ReceiptID
	bad := material
	bad.Received.RequestID = "different-oracle-1"
	body["observation"] = bad
	effectCall(t, s, "POST", "/v1/network-observations", observer, body, 400)
	body["observation"] = material
	provision["scope"] = provenance.Scope{Platform: "hermes", SessionID: "s1", AgentID: "a-1", TaskID: "different-task"}
	other := effectCall(t, s, "POST", "/v1/effect-observers", s.bootAdmin, provision, 201)
	effectCall(t, s, "POST", "/v1/network-observations", other["token"].(string), body, 403)
	record := effectCall(t, s, "POST", "/v1/network-observations", observer, body, 201)
	if record["finding_code"] != "unauthorized_effect_observed" || record["network_observation"] == nil {
		t.Fatal(record)
	}
	retry := effectCall(t, s, "POST", "/v1/network-observations", observer, body, 201)
	if record["signature"] != retry["signature"] {
		t.Fatal("retry changed signed record")
	}
	bad = material
	bad.Received.RequestDigest = strings.Repeat("b", 64)
	body["observation"] = bad
	effectCall(t, s, "POST", "/v1/network-observations", observer, body, 409)
	restarted, err := New(s.d)
	if err != nil {
		t.Fatal(err)
	}
	persisted, err := restarted.effects.Get("network-http", time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if persisted.Signature != record["signature"] {
		t.Fatal("lost signed network material")
	}
	effectCall(t, s, "DELETE", "/v1/effect-observers/"+issued["observer_id"].(string), s.bootAdmin, nil, 204)
	effectCall(t, s, "POST", "/v1/network-observations", observer, body, 403)
}

func TestNetworkCompletionHTTPSignedIntentAndActualReceipt(t *testing.T) {
	for _, mode := range []string{"warn", "block"} {
		t.Run(mode, func(t *testing.T) {
			s, st := newServer(t, mode)
			eng, err := receipt.New(receipt.Options{Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant, EnforcementMode: mode, IntentLookup: receipt.ResolveStore(s.intents), ProvenanceCheck: s.provenance.MatchParameters})
			if err != nil {
				t.Fatal(err)
			}
			s.d.Engine = eng
			oracle, err := effectevidence.NewNetworkOracle("127.0.0.1")
			if err != nil {
				t.Fatal(err)
			}
			defer oracle.Close()
			u, err := url.Parse(oracle.URL())
			if err != nil {
				t.Fatal(err)
			}
			bodyDigest := sha256.Sum256(nil)
			encoded, err := canon.Marshal(map[string]any{"method": "GET", "uri": u.RequestURI(), "body_digest": hex.EncodeToString(bodyDigest[:])})
			if err != nil {
				t.Fatal(err)
			}
			expected := sha256.Sum256(encoded)
			refs := runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "network", Value: u.Hostname()}})
			ref, _ := effectevidence.ResourceReference(refs[0])
			contract := apiIntent()
			contract.SchemaVersion = "intent/v3"
			contract.AllowedTools = []string{"web_fetch"}
			contract.AllowedEffects = []string{"network.request"}
			contract.ResourceConstraints = []intent.ResourceConstraint{{Domain: "network", Operator: "host", Value: u.Hostname()}}
			// Explicit optional provenance isolates this HTTP effect integration fixture.
			constraints := []provenance.Constraint{{ParameterPath: "/url", AllowedSourceTypes: []string{"USER"}, MinimumTrust: "trusted", Required: false}}
			contract.ProvenanceConstraints = &constraints
			reqs := []completion.Requirement{{RequirementID: "receive", EffectType: "network.request", ResourceRef: ref, ExpectedDigest: hex.EncodeToString(expected[:]), ExpectedEndpoint: &completion.Endpoint{Scheme: u.Scheme, Host: u.Hostname(), Port: u.Port()}, MinimumIndependence: "external_independent", MinimumCoverage: "partial"}}
			contract.EffectRequirements = &reqs
			effectCall(t, s, "POST", "/v1/intents", s.bootAdmin, contract, 201)
			// The requirement is committed before any network request occurs.
			pending := effectCall(t, s, "GET", "/v1/tasks/task-1/completion", s.bootAdmin, nil, 200)
			if pending["status"] != "incomplete" {
				t.Fatal(pending)
			}
			effectCall(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, map[string]any{"platform": "hermes", "session_id": "s1", "agent_id": "a-1", "intent_id": "int-api"}, 201)
			d, err := eng.Decide(receipt.Request{Platform: "hermes", SessionID: "s1", AgentID: "a-1", Tool: "web_fetch", ToolCallID: "completion-network", Params: map[string]any{"url": oracle.URL()}})
			if err != nil {
				t.Fatal(err)
			}
			wantAction := "allow"
			wantStatus := "verified"
			if mode == "block" {
				wantAction = "deny"
				wantStatus = "conflicting"
			}
			if d.Action != wantAction {
				t.Fatal(d.Action)
			}
			client := &http.Client{Timeout: 3 * time.Second}
			response, err := client.Get(oracle.URL())
			if err != nil {
				t.Fatal(err)
			}
			response.Body.Close()
			if response.StatusCode != 204 {
				t.Fatal(response.StatusCode)
			}
			material, err := oracle.Material(0, oracle.URL())
			if err != nil {
				t.Fatal(err)
			}
			observer := effectCall(t, s, "POST", "/v1/effect-observers", s.bootAdmin, map[string]any{"source": oracle.Source(), "scope": provenance.Scope{Platform: "hermes", SessionID: "s1", AgentID: "a-1", TaskID: "task-1"}, "expires_in": 60}, 201)["token"].(string)
			effectCall(t, s, "POST", "/v1/network-observations", observer, map[string]any{"observation_id": "completion-net", "action_id": d.Receipt.ActionID, "decision_receipt_id": d.Receipt.ReceiptID, "observation": material}, 201)
			result := effectCall(t, s, "GET", "/v1/tasks/task-1/completion", s.bootAdmin, nil, 200)
			if result["status"] != wantStatus {
				t.Fatal(result)
			}
			// Editing an endpoint under the existing signed Intent ID cannot replace its requirement.
			reqs[0].ExpectedEndpoint.Port = "1"
			effectCall(t, s, "POST", "/v1/intents", s.bootAdmin, contract, 409)
			result = effectCall(t, s, "GET", "/v1/tasks/task-1/completion", s.bootAdmin, nil, 200)
			if result["status"] != wantStatus {
				t.Fatal("intent mutation changed completion", result)
			}
		})
	}
}
