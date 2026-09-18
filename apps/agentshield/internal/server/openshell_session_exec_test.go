package server

// O05 L02 session-execution closed-loop HTTP tests. The OpenShell backend is
// a fake runner behind the documented env-pair invocation
// (SIQ_AS_OPENSHELL_CLI_BIN + SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT), so every
// assertion here is HTTP-单测/模拟 runner 级: it proves the server contract
// (status codes, receipt correlation, outcome honesty, fail-closed rollback)
// against a simulated gateway, not a native host execution.

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/openshell"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

const sessionExecGatewayInfo = "Gateway Info\n  Gateway: siq-openshell-fixture\n  Gateway endpoint: https://127.0.0.1:17671\n  Gateway version: 0.0.104\n"
const sessionExecStatusOutput = "Server Status\n  Gateway: siq-openshell-fixture\n"
const sessionExecVersionOutput = "openshell version 0.0.104\n"

// Base live policy: no network_policies section, mirroring a fresh sandbox.
const sessionExecBasePolicy = `version: 1
filesystem_policy:
  include_workdir: true
  read_only:
  - /usr
  - /lib
  read_write:
  - /sandbox
  - /tmp
landlock:
  compatibility: best_effort
process:
  run_as_user: sandbox
  run_as_group: sandbox
`

const sessionExecEndpoint = "api.github.com:443"

// sessionExecGateway is a minimal stateful fake of `openshell policy` on one
// target: policy get returns the current revision+body, policy set stores the
// submitted file verbatim and bumps the revision. Drift and failure modes are
// switchable per scenario.
type sessionExecGateway struct {
	mu              sync.Mutex
	revision        int
	body            string
	failSet         bool // policy set fails like a transport error
	driftAfterSet   bool // policy set reports success but state does not change
	driftAfterReads int  // after a set, this many reads still see the new state
	postSetReads    int
	setCalls        int
	phase           string
	sandboxID       string
}

func (g *sessionExecGateway) output() string {
	return fmt.Sprintf("Version:      %d\nStatus:       Active\nActive:       %d\nLoaded:       %d ms\n---\n%s", g.revision, g.revision, g.revision, g.body)
}

func (g *sessionExecGateway) runner() openshell.Runner {
	return func(args []string) (int, string, string) {
		g.mu.Lock()
		defer g.mu.Unlock()
		rest := args // injected Runner receives the raw CLI args, no prefix
		switch {
		case len(rest) == 2 && rest[0] == "gateway" && rest[1] == "info":
			return 0, sessionExecGatewayInfo, ""
		case len(rest) == 1 && rest[0] == "status":
			return 0, sessionExecStatusOutput, ""
		case len(rest) == 1 && rest[0] == "--version":
			return 0, sessionExecVersionOutput, ""
		case len(rest) == 4 && rest[0] == "policy" && rest[1] == "get" && rest[3] == "--full":
			if g.driftAfterReads > 0 && g.postSetReads >= g.driftAfterReads {
				// The write landed, then the state drifted back: the
				// verify readback no longer matches the applied digest.
				return 0, fmt.Sprintf("Version:      %d\nStatus:       Active\nActive:       %d\nLoaded:       %d ms\n---\n%s", 1, 1, 1, sessionExecBasePolicy), ""
			}
			if g.driftAfterReads > 0 {
				g.postSetReads++
			}
			return 0, g.output(), ""
		case reflect.DeepEqual(rest, []string{"sandbox", "list", "--limit", "1000", "--output", "json"}):
			phase := g.phase
			if phase == "" {
				phase = "Ready"
			}
			sandboxID := g.sandboxID
			if sandboxID == "" {
				sandboxID = "de99ab6a-8e47-487d-8f69-6e5b6ae9c7a2"
			}
			return 0, fmt.Sprintf(`[{"id":%q,"name":"inst_1","phase":%q,"current_policy_version":%d}]`, sandboxID, phase, g.revision), ""
		case len(rest) == 8 && rest[0] == "policy" && rest[1] == "set" && rest[3] == "--policy" && rest[5] == "--wait" && rest[6] == "--timeout":
			g.setCalls++
			if g.failSet {
				return 1, "", "dial tcp 127.0.0.1:17671: connect: connection refused"
			}
			raw, err := os.ReadFile(rest[4])
			if err != nil {
				return 1, "", "fixture: " + err.Error()
			}
			if !g.driftAfterSet {
				g.revision++
				g.body = string(raw)
				g.postSetReads = 0
			}
			return 0, fmt.Sprintf("Policy version %d submitted (hash: c0ffee11)\n", g.revision), ""
		}
		return 1, "", "unexpected args: " + strings.Join(rest, " ")
	}
}

// newSessionExecServer builds a block-mode server with the fixture grant
// (subject inst_1, endpoint api.github.com:443) deployed and an OpenShell
// client bound to the fake gateway.
func newSessionExecServer(t *testing.T) (*Server, *sessionExecGateway) {
	t.Helper()
	s, st := newServer(t, "block")
	eng, err := receipt.New(receipt.Options{
		Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant,
		EnforcementMode: "block", IntentEnforcement: "optional",
		IntentLookup: receipt.ResolveStore(s.intents), HoldChannel: "openclaw_approval",
	})
	if err != nil {
		t.Fatal(err)
	}
	s.d.Engine = eng
	gw := &sessionExecGateway{revision: 1, body: sessionExecBasePolicy}
	s.d.Openshell = openshell.New(openshell.Options{
		Runner: gw.runner(),
		LookupEnv: func(key string) (string, bool) {
			switch key {
			case "SIQ_AS_OPENSHELL_CLI_BIN":
				return "/fixture/openshell", true
			case "SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT":
				return "https://127.0.0.1:17671", true
			}
			return "", false
		},
		PollInterval: -1,
	})
	skill, err := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "official-like"))
	if err != nil {
		t.Fatal(err)
	}
	admitted := sessionExecPostOK(t, s, "/v1/admit", s.bootAdmin, map[string]any{"path": skill})
	granted := sessionExecPostOK(t, s, "/v1/grants", s.bootAdmin, map[string]any{
		"admission_id": admitted["admission"].(map[string]any)["admission_id"],
		"platform":     "openclaw", "subject_id": "inst_1",
	})
	grantPath := "/v1/grants/" + granted["grant"].(map[string]any)["grant_id"].(string)
	patched := sessionExecPostOK(t, s, grantPath+"/patch-desired", s.bootAdmin, withRevision(map[string]any{
		"models": []string{"fixture-model"},
	}, stateRevision(t, granted)))
	revision := stateRevision(t, patched)
	challenge := sessionExecPostOK(t, s, grantPath+"/challenge", s.bootAdmin, withRevision(nil, revision))["challenge"].(map[string]any)
	approved := sessionExecPostOK(t, s, grantPath+"/approve", s.bootAdmin, withRevision(map[string]any{
		"actor_id": "fixture-admin", "challenge_id": challenge["challenge_id"], "nonce": challenge["nonce"],
	}, revision))
	sessionExecPost(t, s, grantPath+"/deploy", s.bootAdmin, withRevision(nil, stateRevision(t, approved)))
	return s, gw
}

func sessionExecPost(t *testing.T, s *Server, path, bearer string, body any) (int, map[string]any) {
	t.Helper()
	req := loopbackRequest("POST", path, body)
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	var out map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &out)
	return w.Code, out
}

// sessionExecApproveHold drives decide → hold → management approval and
// returns the decision receipt fields.
func sessionExecPostOK(t *testing.T, s *Server, path, bearer string, body any) map[string]any {
	t.Helper()
	code, out := sessionExecPost(t, s, path, bearer, body)
	if code >= 300 {
		t.Fatalf("%s: HTTP %d %v", path, code, out)
	}
	return out
}

func sessionExecApproveHold(t *testing.T, s *Server) map[string]any {
	t.Helper()
	g := s.d.Store.ActiveGrant("openclaw", "inst_1")
	if g == nil {
		t.Fatal("fixture grant missing")
	}
	digest, err := grant.PermissionDigest(*g)
	if err != nil {
		t.Fatal(err)
	}
	params := map[string]any{"command": "siq-openshell-policy-apply", "authorization_urls": []string{"https://" + sessionExecEndpoint}, "openshell_policy": map[string]any{
		"target": "inst_1", "endpoints": []string{sessionExecEndpoint}, "binary_paths": []string{"/usr/bin/curl"}, "expected_revision": "1",
		"grant_id": g.GrantID, "grant_digest": digest, "endpoint_fingerprint": s.d.Openshell.InvocationFingerprint(),
	}}
	decision := sessionExecPostOK(t, s, "/v1/decide", token, map[string]any{
		"platform": "openclaw", "session_id": nativeOpenClawSession(t, "hold-session"), "agent_id": "inst_1",
		"tool": "exec", "tool_call_id": "held-call", "params": params,
	})
	if decision["action"] != "hold" {
		t.Fatalf("fixture must hold exec: %v", decision)
	}
	resolved := sessionExecPostOK(t, s, "/v1/hold/"+decision["receipt_id"].(string), s.bootAdmin,
		map[string]any{"approve": true, "actor_id": "fixture-admin"})
	if resolved["status"] != "approved" && resolved["receipt_id"] == nil {
		t.Fatalf("hold approval failed: %v", resolved)
	}
	decision["fixture_params"] = params
	return decision
}

func sessionExecBody(decision map[string]any) map[string]any {
	session, _ := intent.OpenClawSessionID("hold-session", "11111111-1111-4111-8111-111111111111")
	return map[string]any{
		"schema_version": "hold-execution-reserve/v1", "platform": "openclaw",
		"session_id": session, "agent_id": "inst_1", "tool": "exec",
		"original_tool_call_id": "held-call", "retry_tool_call_id": "held-call-retry",
		"action_id": decision["action_id"], "decision_receipt_id": decision["receipt_id"],
		"params":            decision["fixture_params"],
		"target":            "inst_1",
		"endpoints":         []string{sessionExecEndpoint},
		"expected_revision": "1",
		"binary_paths":      []string{"/usr/bin/curl"},
	}
}

// sessionExecHoldStatus reads the pre-reserve hold status.
func sessionExecHoldStatus(t *testing.T, s *Server, decision map[string]any) string {
	t.Helper()
	code, status := sessionExecPost(t, s, "/v1/hold-status", token, map[string]any{
		"platform": "openclaw", "session_id": nativeOpenClawSession(t, "hold-session"), "agent_id": "inst_1",
		"tool": "exec", "tool_call_id": "held-call", "action_id": decision["action_id"],
		"decision_receipt_id": decision["receipt_id"],
		"params":              decision["fixture_params"],
	})
	if code != 200 {
		t.Fatalf("hold-status: HTTP %d %v", code, status)
	}
	return status["status"].(string)
}

// sessionExecReservationStatus reads the post-reserve execution status.
func sessionExecReservationStatus(t *testing.T, s *Server, decision, reservation map[string]any) string {
	t.Helper()
	code, status := sessionExecPost(t, s, "/v1/hold-executions/status", token, map[string]any{
		"schema_version": "hold-execution-status-request/v1", "platform": "openclaw",
		"session_id": nativeOpenClawSession(t, "hold-session"), "agent_id": "inst_1", "tool": "exec",
		"retry_tool_call_id": "held-call-retry", "action_id": decision["action_id"],
		"decision_receipt_id":    decision["receipt_id"],
		"reservation_receipt_id": reservation["reservation_receipt_id"],
		"params":                 decision["fixture_params"],
	})
	if code != 200 {
		t.Fatalf("hold-executions/status: HTTP %d %v", code, status)
	}
	return status["status"].(string)
}

func TestOpenShellSessionExecAuthAndPrechecksBeforeReserve(t *testing.T) {
	s, _ := newSessionExecServer(t)
	decision := sessionExecApproveHold(t, s)
	body := sessionExecBody(decision)

	// No credential.
	if code, _ := sessionExecPost(t, s, "/v1/openshell/session-executions", "", body); code != 401 {
		t.Fatalf("no bearer: HTTP %d", code)
	}
	// Admin token is not a decision credential.
	if code, _ := sessionExecPost(t, s, "/v1/openshell/session-executions", s.bootAdmin, body); code != 401 {
		t.Fatalf("admin token on decision route: HTTP %d", code)
	}
	// Malformed revision never reaches the reserve.
	bad := sessionExecBody(decision)
	bad["expected_revision"] = "01"
	if code, _ := sessionExecPost(t, s, "/v1/openshell/session-executions", token, bad); code != 400 {
		t.Fatalf("non-canonical revision: HTTP %d", code)
	}
	// Relative binary path is a request-shape rejection.
	bad = sessionExecBody(decision)
	bad["binary_paths"] = []string{"curl"}
	if code, _ := sessionExecPost(t, s, "/v1/openshell/session-executions", token, bad); code != 400 {
		t.Fatalf("relative binary path: HTTP %d", code)
	}
	// Cross-target: target has no deployed grant. 403 BEFORE the reserve, so
	// the human approval stays intact.
	cross := sessionExecBody(decision)
	cross["target"] = "other-agent"
	if code, resp := sessionExecPost(t, s, "/v1/openshell/session-executions", token, cross); code != 403 || resp["reason_code"] != "openshell_operation_binding_mismatch" {
		t.Fatalf("cross target: HTTP %d %v", code, resp)
	}
	// Endpoint outside the grant facts is refused too.
	ep := sessionExecBody(decision)
	ep["endpoints"] = []string{"evil.example.com:443"}
	if code, resp := sessionExecPost(t, s, "/v1/openshell/session-executions", token, ep); code != 403 || resp["reason_code"] != "openshell_operation_binding_mismatch" {
		t.Fatalf("unauthorized endpoint: HTTP %d %v", code, resp)
	}
	if got := sessionExecHoldStatus(t, s, decision); got != "approved" {
		t.Fatalf("rejections must not consume the approval, status=%s", got)
	}
}

func TestOpenShellSessionExecRequiresL3Backend(t *testing.T) {
	s, _ := newSessionExecServer(t)
	decision := sessionExecApproveHold(t, s)
	body := sessionExecBody(decision)

	// Unconfigured backend: 503, never a native fallback.
	s.d.Openshell = nil
	code, resp := sessionExecPost(t, s, "/v1/openshell/session-executions", token, body)
	if code != 503 {
		t.Fatalf("unconfigured backend: HTTP %d %v", code, resp)
	}
	// Backend present but probe fails (not L3): still 503.
	s.d.Openshell = openshell.New(openshell.Options{Runner: func([]string) (int, string, string) {
		return 1, "", "not an openshell gateway"
	}, PollInterval: -1})
	if code, resp := sessionExecPost(t, s, "/v1/openshell/session-executions", token, body); code != 503 {
		t.Fatalf("probe-failing backend: HTTP %d %v", code, resp)
	}
	if got := sessionExecHoldStatus(t, s, decision); got != "approved" {
		t.Fatalf("L3 gate must not consume the approval, status=%s", got)
	}
}

func TestOpenShellSessionExecHappyPathCorrelationAndRollback(t *testing.T) {
	s, gw := newSessionExecServer(t)
	decision := sessionExecApproveHold(t, s)
	code, resp := sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(decision))
	if code != 200 {
		t.Fatalf("execute: HTTP %d %v", code, resp)
	}
	if resp["ok"] != true || resp["operation_id"] == "" || resp["binding_evidence_id"] == "" {
		t.Fatalf("missing execution identifiers: %v", resp)
	}
	if resp["binding_evidence_persisted"] != true {
		t.Fatalf("binding evidence not persisted: %v", resp)
	}
	if resp["observation_receipt_id"] == "" {
		t.Fatalf("observation not recorded: %v", resp)
	}
	receiptOut := resp["receipt"].(map[string]any)
	if receiptOut["backend_revision"] != "2" {
		t.Fatalf("backend revision: %v", receiptOut)
	}
	readback := resp["effective_readback"].(map[string]any)
	if readback["revision"] != "2" {
		t.Fatalf("readback revision: %v", readback)
	}
	gw.mu.Lock()
	wroteRevision, wroteBody, setCalls := gw.revision, gw.body, gw.setCalls
	gw.mu.Unlock()
	if wroteRevision != 2 || !strings.Contains(wroteBody, "host: api.github.com") || !strings.Contains(wroteBody, "port: 443") || setCalls != 1 {
		t.Fatalf("gateway state after execute: rev=%d setCalls=%d body=%q", wroteRevision, setCalls, wroteBody)
	}
	if got := sessionExecReservationStatus(t, s, decision, resp["reservation"].(map[string]any)); got != "completed" {
		t.Fatalf("reservation status after successful execution: %s", got)
	}
	// Step ⑥: the signed chain must verify and correlate the reservation and
	// observation.
	chain, err := s.d.Chain.Read()
	if err != nil {
		t.Fatal(err)
	}
	if err := receipt.Verify(chain, s.d.Key.Public()); err != nil {
		t.Fatalf("receipt chain broken: %v", err)
	}
	kinds := map[string]bool{}
	for _, rec := range chain {
		kinds[rec.RecordType] = true
	}
	// ReserveHoldExecution reuses the signed hold_reservation record type with
	// reason hold_execution_reserved; the observation is its own record.
	reserved := false
	for _, rec := range chain {
		if rec.RecordType == "hold_reservation" && rec.ReasonCode == "hold_execution_reserved" {
			reserved = true
		}
	}
	if !reserved || !kinds["observation"] || !kinds["decision"] {
		t.Fatalf("chain missing reservation/observation records: %v", kinds)
	}
	// Binding evidence is durable in the store.
	evID := resp["binding_evidence_id"].(string)
	if _, err := os.Stat(filepath.Join(s.d.Store.Dir, "evidence", evID+".json")); err != nil {
		t.Fatalf("binding evidence file: %v", err)
	}

	// Step ⑤ rollback: identity must match the recorded execution.
	reservation := resp["reservation"].(map[string]any)
	rollback := func(action string) (int, map[string]any) {
		return sessionExecPost(t, s, "/v1/openshell/session-executions/rollback", s.bootAdmin, map[string]any{
			"reservation_receipt_id": reservation["reservation_receipt_id"],
			"action_id":              action,
			"decision_receipt_id":    decision["receipt_id"],
			"actor_id":               "fixture-admin",
		})
	}
	if code, resp := rollback("wrong-action"); code != 403 {
		t.Fatalf("mismatched rollback identity: HTTP %d %v", code, resp)
	}
	code, resp = rollback(decision["action_id"].(string))
	if code != 200 {
		t.Fatalf("rollback: HTTP %d %v", code, resp)
	}
	if resp["outcome"] != "occurred" {
		t.Fatalf("rollback outcome: %v", resp)
	}
	if resp["reconciliation_note"] == "" {
		t.Fatalf("rollback after a signed observation must surface the refused reconciliation: %v", resp)
	}
	gw.mu.Lock()
	restoredRevision, restoredBody := gw.revision, gw.body
	gw.mu.Unlock()
	if restoredRevision != 3 || strings.Contains(restoredBody, sessionExecEndpoint) {
		t.Fatalf("gateway not restored: rev=%d body contains endpoint=%v", restoredRevision, strings.Contains(restoredBody, sessionExecEndpoint))
	}
	// Fail-closed: a consumed operation cannot be rolled back twice.
	if code, resp := rollback(decision["action_id"].(string)); code != 409 || resp["reason_code"] != "rollback_refused" {
		t.Fatalf("second rollback: HTTP %d %v", code, resp)
	}
}

func TestOpenShellSessionExecSetFailureStaysUncertain(t *testing.T) {
	s, gw := newSessionExecServer(t)
	gw.mu.Lock()
	gw.failSet = true
	gw.mu.Unlock()
	decision := sessionExecApproveHold(t, s)
	code, resp := sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(decision))
	if code != 502 || resp["reason_code"] != "execution_uncertain" || resp["execution_uncertain"] != true {
		t.Fatalf("transport failure: HTTP %d %v", code, resp)
	}
	if got := sessionExecReservationStatus(t, s, decision, resp["reservation"].(map[string]any)); got != "uncertain" {
		t.Fatalf("uncertain execution must keep the reservation unresolved, status=%s", got)
	}
	// Never auto-replay: a retry is refused because the reservation exists.
	if code, resp := sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(decision)); code != 409 {
		t.Fatalf("replay after uncertain: HTTP %d %v", code, resp)
	}
	gw.mu.Lock()
	setCalls := gw.setCalls
	gw.mu.Unlock()
	if setCalls != 1 {
		t.Fatalf("replay must not reach the gateway, setCalls=%d", setCalls)
	}
}

func TestOpenShellSessionExecPostWriteDriftStaysUncertain(t *testing.T) {
	s, gw := newSessionExecServer(t)
	gw.mu.Lock()
	gw.driftAfterReads = 1
	gw.mu.Unlock()
	decision := sessionExecApproveHold(t, s)
	code, resp := sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(decision))
	if code != 409 || resp["reason_code"] != "execution_uncertain" || resp["execution_uncertain"] != true {
		t.Fatalf("post-write verify failure: HTTP %d %v", code, resp)
	}
	// The write reached the gateway and verify passed, then drifted: the
	// receipt carries the backend revision (409, not the unknown-outcome 502).
	if resp["receipt"].(map[string]any)["backend_revision"] != "2" {
		t.Fatalf("post-write drift must carry the applied revision: %v", resp)
	}
	if got := sessionExecReservationStatus(t, s, decision, resp["reservation"].(map[string]any)); got != "uncertain" {
		t.Fatalf("post-write drift status: %s", got)
	}
}

func TestOpenShellSessionExecRevisionConflictReconcilesNotOccurred(t *testing.T) {
	s, gw := newSessionExecServer(t)
	decision := sessionExecApproveHold(t, s)
	// Concurrent change between approval and execution: expected_revision is
	// now stale.
	gw.mu.Lock()
	gw.revision++
	gw.mu.Unlock()
	code, resp := sessionExecPost(t, s, "/v1/openshell/session-executions", token, sessionExecBody(decision))
	if code != 409 || resp["reason_code"] != "revision_conflict" {
		t.Fatalf("stale revision: HTTP %d %v", code, resp)
	}
	if resp["execution"] != receipt.HoldExecutionNotOccurred {
		t.Fatalf("CAS rejection is provably no-write: %v", resp)
	}
	rec, _ := resp["reconciliation"].(map[string]any)
	if rec == nil || rec["status"] != "cancelled" {
		t.Fatalf("auto reconcile not_occurred: %v", resp)
	}
	gw.mu.Lock()
	setCalls := gw.setCalls
	gw.mu.Unlock()
	if setCalls != 0 {
		t.Fatalf("revision conflict must be zero-write, setCalls=%d", setCalls)
	}
	if got := sessionExecReservationStatus(t, s, decision, resp["reservation"].(map[string]any)); got != "cancelled" {
		t.Fatalf("status after reconcile: %s", got)
	}
}

func TestOpenShellSessionPreviewIsReadOnly(t *testing.T) {
	s, _ := newSessionExecServer(t)
	if code, _ := sessionExecPost(t, s, "/v1/openshell/session-executions/preview", "", map[string]any{"target": "inst_1"}); code != 401 {
		t.Fatalf("preview without bearer: HTTP %d", code)
	}
	// Decision token is not an admin credential.
	if code, _ := sessionExecPost(t, s, "/v1/openshell/session-executions/preview", token, map[string]any{"target": "inst_1"}); code != 403 {
		t.Fatalf("decision token on admin route: HTTP %d", code)
	}
	code, resp := sessionExecPost(t, s, "/v1/openshell/session-executions/preview", s.bootAdmin, map[string]any{"target": "inst_1"})
	if code != 200 {
		t.Fatalf("preview: HTTP %d %v", code, resp)
	}
	if resp["execution_constraints_verified"] != false {
		t.Fatalf("preview must not claim verified execution limits: %v", resp)
	}
	endpoints, _ := resp["authorized_endpoints"].([]any)
	found := false
	for _, ep := range endpoints {
		if ep == sessionExecEndpoint {
			found = true
		}
	}
	if !found {
		t.Fatalf("authorized endpoints from grant facts: %v", endpoints)
	}
	live, _ := resp["live"].(map[string]any)
	if live == nil || live["revision"] != "1" {
		t.Fatalf("live readback: %v", resp)
	}
	if code, resp := sessionExecPost(t, s, "/v1/openshell/session-executions/preview", s.bootAdmin, map[string]any{"target": "other-agent"}); code != 403 || resp["reason_code"] != "target_not_authorized" {
		t.Fatalf("unauthorized preview: HTTP %d %v", code, resp)
	}
}
