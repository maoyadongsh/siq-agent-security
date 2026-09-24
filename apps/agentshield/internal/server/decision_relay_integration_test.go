package server

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/decisionrelay"
)

type relayServerTransport struct {
	handler http.Handler
	calls   int
}

func (transport *relayServerTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	transport.calls++
	request.RemoteAddr = "127.0.0.1:54321"
	recorder := httptest.NewRecorder()
	transport.handler.ServeHTTP(recorder, request)
	return recorder.Result(), nil
}

func relayConfig(identity, instance, agent, sessionNamespace string) decisionrelay.Config {
	return decisionrelay.Config{
		SchemaVersion: decisionrelay.SchemaVersion,
		Binding: decisionrelay.Binding{
			Platform: "hermes", RuntimeIdentityID: identity, InstanceID: instance, AgentID: agent,
			SandboxNamespace: "siq-openshell-dev", SandboxName: "siq-analysis-run-001",
			SandboxID: "123e4567-e89b-12d3-a456-426614174000", SandboxGeneration: 1,
			Profile: "siq_analysis", ScopeID: strings.Repeat("2", 24), RunID: "run-001",
			SessionNamespace: sessionNamespace,
		},
		Listener: decisionrelay.Listener{
			URL: decisionrelay.SandboxURL, InheritedFD: 3,
			Transport: decisionrelay.ListenerTransport, TargetContainerID: strings.Repeat("a", 64),
			NetworkName: "siq-openshell-dev", NetworkID: strings.Repeat("b", 64),
			GatewayIP: "172.23.0.1", HostAlias: "host.openshell.internal",
		},
		Upstream: decisionrelay.LoopbackURL, AllowedRoutes: append([]string{}, decisionrelay.AllowedRoutes...),
		MaxRequestBytes: decisionrelay.MaxPayloadBytes, MaxResponseBytes: decisionrelay.MaxPayloadBytes,
		UpstreamTimeoutMS: 5000,
	}
}

func relayCall(t *testing.T, relay http.Handler, path, credential string, body any) (int, map[string]any) {
	t.Helper()
	raw, err := json.Marshal(body)
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(http.MethodPost, decisionrelay.LoopbackURL+path, bytes.NewReader(raw))
	request.Header.Set("Authorization", "Bearer "+credential)
	recorder := httptest.NewRecorder()
	relay.ServeHTTP(recorder, request)
	result := map[string]any{}
	responseRaw, _ := io.ReadAll(recorder.Result().Body)
	_ = json.Unmarshal(responseRaw, &result)
	return recorder.Code, result
}

func TestOpenShellDecisionRelayUsesDaemonSessionAndRevocationAuthority(t *testing.T) {
	testOpenShellRelayAuthority(t, decisionrelay.SchemaVersion)
}

func TestOpenShellCandidateDecisionRelayUsesDaemonSessionAndRevocationAuthority(t *testing.T) {
	testOpenShellRelayAuthority(t, decisionrelay.CandidateSchemaVersion)
}

func TestOpenShellIsolatedDecisionRelayUsesDaemonSessionAndRevocationAuthority(t *testing.T) {
	testOpenShellRelayAuthority(t, decisionrelay.IsolatedSchemaVersion)
}

func testOpenShellRelayAuthority(t *testing.T, version string) {
	t.Helper()
	server, issued, credential, agent := managedIdentityFixture(t, "block")
	identity := issued["identity"].(map[string]any)
	identityID := identity["identity_id"].(string)
	instanceID := identity["instance_id"].(string)
	scope := strings.Repeat("2", 24)
	namespace := "siq:openshell:pool:" + scope + ":run-001:siq_analysis"
	session := namespace + ":" + strings.Repeat("3", 64)
	transport := &relayServerTransport{handler: server.Handler()}
	client := &http.Client{Transport: transport}
	cfg := relayConfig(identityID, instanceID, agent, namespace)
	if version != decisionrelay.SchemaVersion {
		cfg.SchemaVersion = version
		cfg.Binding.SandboxNamespace = "siq-openshell-scope-validation"
		cfg.Binding.SandboxName = "siq-qwen38-scoped-0123456789abcdef"
	}
	if version == decisionrelay.IsolatedSchemaVersion {
		cfg.Upstream = decisionrelay.IsolatedLoopbackURL
		server.d.ListenPort = 47811
	}
	relay, err := decisionrelay.NewWithClient(cfg, client)
	if err != nil {
		t.Fatal(err)
	}

	enroll := map[string]any{
		"schema_version": "local-runtime-session-enroll/v1", "session_id": session,
	}
	if code, out := relayCall(t, relay, "/v1/runtime-sessions", credential, enroll); code != 200 || out["identity_id"] != identityID {
		t.Fatal("relay enrollment failed", code, out)
	}
	decision := map[string]any{
		"platform": "hermes", "agent_id": agent, "session_id": session,
		"tool": "read_file", "params": map[string]any{"path": "/work/public/report"},
	}
	if code, out := relayCall(t, relay, "/v1/decide", credential, decision); code != 200 || out["action"] != "allow" {
		t.Fatal("relay decision failed", code, out)
	}

	before := transport.calls
	if code, _ := relayCall(t, relay, "/v1/runtime-identities", credential, decision); code != 404 || transport.calls != before {
		t.Fatal("management route reached daemon", code, transport.calls-before)
	}
	decision["session_id"] = namespace + ":" + strings.Repeat("4", 64)
	if code, _ := relayCall(t, relay, "/v1/decide", credential, decision); code != 401 {
		t.Fatal("unenrolled cross-session request accepted", code)
	}
	decision["session_id"] = session
	revokeRequest := loopbackRequest("POST", cfg.Upstream+"/v1/runtime-identities/"+identityID+"/revoke", map[string]any{
		"schema_version": "local-runtime-identity-revoke/v1", "actor_id": "operator",
	})
	revokeRequest.Host = revokeRequest.URL.Host
	revokeRequest.Header.Set("Authorization", "Bearer "+server.bootAdmin)
	revokeResponse := httptest.NewRecorder()
	server.Handler().ServeHTTP(revokeResponse, revokeRequest)
	var revoked map[string]any
	_ = json.Unmarshal(revokeResponse.Body.Bytes(), &revoked)
	if revokeResponse.Code != 200 || revoked["revoked"] != true {
		t.Fatal("fixture revocation failed", revokeResponse.Code, revoked)
	}
	if code, _ := relayCall(t, relay, "/v1/decide", credential, decision); code != 401 {
		t.Fatal("revoked credential accepted through relay", code)
	}
}
