package server

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/openshell"
)

// Server-side tests for the real task-execution route.
//
// These drive the SAME production handler the daemon serves. The only injected
// component is the openshell.TaskRunner seam, which replaces the OS spawn and
// nothing else: every binding, ordering, refusal and outcome-classification
// decision below is made by production code, so a green test here cannot come
// from a test-only bypass.

// taskSpy is a fake openshell.TaskRunner. It records what the executor asked to
// run and answers with a per-call scripted result.
type taskSpy struct {
	mu      sync.Mutex
	calls   int
	args    [][]string
	timeout []time.Duration
	limit   []int
	// next scripts the result of call N (1-based). nil means "rc=0, ok".
	next func(call int) openshell.TaskRunResult
}

func (s *taskSpy) runner() openshell.TaskRunner {
	return func(ctx context.Context, args []string, timeout time.Duration, limit int) openshell.TaskRunResult {
		s.mu.Lock()
		s.calls++
		n := s.calls
		s.args = append(s.args, append([]string(nil), args...))
		s.timeout = append(s.timeout, timeout)
		s.limit = append(s.limit, limit)
		next := s.next
		s.mu.Unlock()
		if next == nil {
			return openshell.TaskRunResult{ExitCode: 0, Stdout: "siq-task-ok\n", Spawned: true}
		}
		return next(n)
	}
}

func (s *taskSpy) callCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.calls
}

// newTaskExecServer reuses the policy-apply fixture (a deployed grant for
// subject inst_1, endpoint api.github.com:443, fake gateway) and re-binds the
// OpenShell client with a fake TaskRunner alongside the fake CLI runner.
func newTaskExecServer(t *testing.T, spy *taskSpy) (*Server, *sessionExecGateway) {
	t.Helper()
	s, gw := newSessionExecServer(t)
	s.d.Openshell = openshell.New(openshell.Options{
		Runner:     gw.runner(),
		TaskRunner: spy.runner(),
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
	// A task requires a prior, separately approved policy deployment whose
	// --wait acknowledgement belongs to this endpoint and exact revision.
	base, err := s.d.Openshell.ReadEffective(taskExecTarget())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.d.Openshell.ApplyNetwork(taskExecTarget(), []openshell.NetworkRule{{
		Endpoint: sessionExecEndpoint, Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"},
	}}, base.Revision); err != nil {
		t.Fatal(err)
	}
	return s, gw
}

func taskExecTarget() string { return "inst_1" }

var taskExecArgv = []string{"/bin/echo", "siq-task-ok"}

// taskExecParams builds the approved parameter object from live signed state.
// It is assembled HERE rather than by calling canonicalTaskParams: a test that
// asks production code to produce the value it is about to verify proves
// nothing about the contract.
func taskExecParams(t *testing.T, s *Server) map[string]any {
	t.Helper()
	g := s.d.Store.ActiveGrant("openclaw", taskExecTarget())
	if g == nil {
		t.Fatal("fixture grant missing")
	}
	digest, err := grant.PermissionDigest(*g)
	if err != nil {
		t.Fatal(err)
	}
	snap, err := s.d.Openshell.ReadEffective(taskExecTarget())
	if err != nil {
		t.Fatal(err)
	}
	return map[string]any{
		"command":            openshellTaskCommand,
		"target":             g.Subject.ID,
		"argv":               taskExecArgv,
		"workdir":            "",
		"timeout_seconds":    openshellTaskDefaultTimeoutSeconds,
		"output_limit_bytes": openshellTaskDefaultOutputLimit,
		"policy_revision":    snap.Revision,
		"policy_digest":      snap.PolicyDigest,
		"authorization_urls": []string{"https://" + sessionExecEndpoint},
		"openshell_task": map[string]any{
			"target": g.Subject.ID, "grant_id": g.GrantID, "grant_digest": digest,
			"endpoint_fingerprint": s.d.Openshell.InvocationFingerprint(),
			"sandbox_id":           "de99ab6a-8e47-487d-8f69-6e5b6ae9c7a2",
		},
	}
}

// taskExecApproveHold drives decide -> hold -> management approval for one exec
// tool call carrying the task command, and returns the decision fields plus the
// params the human actually approved.
func taskExecApproveHold(t *testing.T, s *Server) map[string]any {
	t.Helper()
	params := taskExecParams(t, s)
	decision := sessionExecPostOK(t, s, "/v1/decide", token, map[string]any{
		"platform": "openclaw", "session_id": "hold-session", "agent_id": taskExecTarget(),
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

func taskExecBody(decision map[string]any) map[string]any {
	p := decision["fixture_params"].(map[string]any)
	return map[string]any{
		"schema_version": openshellTaskSchemaRequest, "platform": "openclaw",
		"session_id": "hold-session", "agent_id": taskExecTarget(), "tool": "exec",
		"original_tool_call_id": "held-call", "retry_tool_call_id": "held-call-retry",
		"action_id": decision["action_id"], "decision_receipt_id": decision["receipt_id"],
		"target":          taskExecTarget(),
		"argv":            taskExecArgv,
		"policy_revision": p["policy_revision"],
		"policy_digest":   p["policy_digest"],
		"network_targets": []string{sessionExecEndpoint},
		"params":          p,
	}
}

// taskExecPost always presents the supplied bearer verbatim. The shared call()
// helper rewrites an unknown path to the boot admin token, which would turn
// every 401 expectation below into a false pass.
func taskExecPost(t *testing.T, s *Server, bearer string, body any) (int, map[string]any) {
	t.Helper()
	return sessionExecPost(t, s, "/v1/openshell/task-executions", bearer, body)
}

func cloneJSON(t *testing.T, v any) map[string]any {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

// decodeTaskRequest turns a wire body into the request struct exactly the way
// the handler does, so the binding checks below run against the same shape a
// real client produces.
func decodeTaskRequest(t *testing.T, body map[string]any) openshellTaskExecuteRequest {
	t.Helper()
	raw, err := json.Marshal(body)
	if err != nil {
		t.Fatal(err)
	}
	var req openshellTaskExecuteRequest
	if err := json.Unmarshal(raw, &req); err != nil {
		t.Fatal(err)
	}
	return req
}

func readEvidence(t *testing.T, s *Server, id string) map[string]any {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(s.d.Store.Dir, "evidence", id+".json"))
	if err != nil {
		t.Fatalf("evidence %s: %v", id, err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	return doc
}

// TestOpenShellTaskExecAuthAndShapeBeforeReserve proves the edge refuses before
// any approval can be spent, and that only a decision credential may spend a
// hold: an administrator login is not execution authorization.
func TestOpenShellTaskExecAuthAndShapeBeforeReserve(t *testing.T) {
	spy := &taskSpy{}
	s, _ := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)
	body := taskExecBody(decision)

	if code, out := taskExecPost(t, s, "", body); code != 401 {
		t.Fatalf("unauthenticated: HTTP %d %v", code, out)
	}
	if code, out := taskExecPost(t, s, s.bootAdmin, body); code != 401 {
		t.Fatalf("an admin session must not execute a task: HTTP %d %v", code, out)
	}
	req := loopbackRequest("GET", "/v1/openshell/task-executions", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	if w.Code != 405 {
		t.Fatalf("GET: HTTP %d", w.Code)
	}

	tooManyTargets := make([]string, 65)
	for i := range tooManyTargets {
		tooManyTargets[i] = sessionExecEndpoint
	}
	bad := map[string]map[string]any{
		"sibling contract version":     {"schema_version": "hold-execution-reserve/v1"},
		"unknown contract version":     {"schema_version": "openshell-task-execution-request/v2"},
		"empty argv":                   {"argv": []string{}},
		"too many argv elements":       {"argv": append(make([]string, 256), "x")},
		"empty argv element":           {"argv": []string{"/bin/echo", ""}},
		"nul in argv":                  {"argv": []string{"/bin/echo", "a\x00b"}},
		"traversal workdir":            {"workdir": "/tmp/../etc"},
		"relative workdir":             {"workdir": "tmp/x"},
		"raw output requested":         {"store_raw_output": true},
		"timeout out of range":         {"timeout_seconds": 901},
		"output limit below the floor": {"output_limit_bytes": 1},
		"output limit above ceiling":   {"output_limit_bytes": 1048577},
		"non hex policy digest":        {"policy_digest": strings.Repeat("z", 64)},
		"short policy digest":          {"policy_digest": "abc"},
		"zero policy revision":         {"policy_revision": "0"},
		"endpoint without port":        {"network_targets": []string{"api.github.com"}},
		"endpoint with path":           {"network_targets": []string{"api.github.com:443/x"}},
		"endpoint port above 65535":    {"network_targets": []string{"api.github.com:99999"}},
		"endpoint non canonical port":  {"network_targets": []string{"api.github.com:0443"}},
		"too many network targets":     {"network_targets": tooManyTargets},
	}
	for name, patch := range bad {
		mutated := cloneJSON(t, body)
		for k, v := range patch {
			mutated[k] = v
		}
		code, out := taskExecPost(t, s, token, mutated)
		if code != 400 || out["error"] != "invalid_openshell_task_shape" {
			t.Fatalf("%s: HTTP %d %v", name, code, out)
		}
	}
	if spy.callCount() != 0 {
		t.Fatalf("no rejected submission may reach the runner, got %d calls", spy.callCount())
	}
	// After all of that the human approval is still unconsumed.
	if got := sessionExecHoldStatus(t, s, decision); got != "approved" {
		t.Fatalf("the approval was burned by a rejected submission: %q", got)
	}
}

// TestOpenShellTaskExecRequiresL3Backend proves a missing or unbound backend is
// a refusal, never a native fallback.
func TestOpenShellTaskExecRequiresL3Backend(t *testing.T) {
	spy := &taskSpy{}
	s, _ := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)
	body := taskExecBody(decision)

	s.d.Openshell = openshell.New(openshell.Options{
		Runner:    func([]string) (int, string, string) { return 1, "", "unbound" },
		LookupEnv: func(string) (string, bool) { return "", false },
	})
	code, out := taskExecPost(t, s, token, body)
	if code != 503 {
		t.Fatalf("unbound backend: HTTP %d %v", code, out)
	}
	if spy.callCount() != 0 {
		t.Fatal("a missing backend must not fall back to a local spawn")
	}
	if got := sessionExecHoldStatus(t, s, decision); got != "approved" {
		t.Fatalf("backend unavailability must not burn the approval: %q", got)
	}
}

// A policy get may report an exact approved revision while the sandbox is not
// Ready. Refuse before consuming the one-use approval.
func TestOpenShellTaskExecUnloadedPolicyKeepsApproval(t *testing.T) {
	spy := &taskSpy{}
	s, gw := newSessionExecServer(t)
	gw.phase = "Provisioning"
	// Use a unique endpoint identity so another fixture's successful set
	// cannot supply this test's process-local load proof.
	s.d.Openshell = openshell.New(openshell.Options{
		Runner: gw.runner(), TaskRunner: spy.runner(), PollInterval: -1,
		LookupEnv: func(key string) (string, bool) {
			switch key {
			case "SIQ_AS_OPENSHELL_CLI_BIN":
				return "/fixture/openshell", true
			case "SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT":
				return "https://127.0.0.1:19471", true
			}
			return "", false
		},
	})
	decision := taskExecApproveHold(t, s)
	code, out := taskExecPost(t, s, token, taskExecBody(decision))
	if code != 409 || out["reason_code"] != "openshell_task_instance_unconfirmed" {
		t.Fatalf("unconfirmed load: HTTP %d %v", code, out)
	}
	if spy.callCount() != 0 {
		t.Fatal("unconfirmed load reached task runner")
	}
	if got := sessionExecHoldStatus(t, s, decision); got != "approved" {
		t.Fatalf("unconfirmed load consumed approval: %q", got)
	}
}

// TestOpenShellTaskExecAcceptsExactlyTheDocumentedParams is the anti-tautology
// case: the params map written out against the public contract must bind, and
// every mutation of an approved field must not.
func TestOpenShellTaskExecAcceptsExactlyTheDocumentedParams(t *testing.T) {
	spy := &taskSpy{}
	s, _ := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)

	if _, err := s.validateOpenShellTaskExecutionBinding(decodeTaskRequest(t, taskExecBody(decision))); err != nil {
		t.Fatalf("the documented params must bind: %v", err)
	}

	mutations := map[string]func(p map[string]any){
		"argv changed":          func(p map[string]any) { p["argv"] = []string{"/bin/echo", "different"} },
		"argv appended":         func(p map[string]any) { p["argv"] = []string{"/bin/echo", "siq-task-ok", "extra"} },
		"timeout widened":       func(p map[string]any) { p["timeout_seconds"] = 900 },
		"output limit widened":  func(p map[string]any) { p["output_limit_bytes"] = 1048576 },
		"policy revision moved": func(p map[string]any) { p["policy_revision"] = "999" },
		"policy digest changed": func(p map[string]any) { p["policy_digest"] = strings.Repeat("a", 64) },
		"target changed":        func(p map[string]any) { p["target"] = "inst_2" },
		"workdir added":         func(p map[string]any) { p["workdir"] = "/tmp" },
		"extra parameter":       func(p map[string]any) { p["extra"] = true },
		"raw output asked":      func(p map[string]any) { p["store_raw_output"] = true },
		"url appended": func(p map[string]any) {
			p["authorization_urls"] = []string{"https://" + sessionExecEndpoint, "https://evil.example:443"}
		},
		"command changed": func(p map[string]any) { p["command"] = "siq-openshell-policy-apply" },
		"grant id changed": func(p map[string]any) {
			p["openshell_task"].(map[string]any)["grant_id"] = "grant-other"
		},
		"endpoint fingerprint changed": func(p map[string]any) {
			p["openshell_task"].(map[string]any)["endpoint_fingerprint"] = strings.Repeat("0", 64)
		},
		"sandbox id changed": func(p map[string]any) {
			p["openshell_task"].(map[string]any)["sandbox_id"] = "103b9f8a-10f0-4fa0-9146-b50c6e0fb16c"
		},
		"sandbox id removed": func(p map[string]any) {
			delete(p["openshell_task"].(map[string]any), "sandbox_id")
		},
		"backend binding removed": func(p map[string]any) { delete(p, "openshell_task") },
	}
	for name, mutate := range mutations {
		attempt := decodeTaskRequest(t, taskExecBody(decision))
		params := cloneJSON(t, attempt.Params)
		mutate(params)
		attempt.Params = params
		_, err := s.validateOpenShellTaskExecutionBinding(attempt)
		if err == nil {
			t.Fatalf("%s: mutated params must not bind", name)
		}
		if err.Error() != "openshell_task_binding_mismatch" {
			t.Fatalf("%s: expected a binding mismatch, got %v", name, err)
		}
	}
}

// A new sandbox with the same name and policy bytes is a different execution
// principal. The approval must be rejected before reservation even when the
// target, grant, policy revision and digest still match.
func TestOpenShellTaskExecRefusesSameNameInstanceReplacement(t *testing.T) {
	spy := &taskSpy{}
	s, gw := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)
	gw.mu.Lock()
	gw.sandboxID = "103b9f8a-10f0-4fa0-9146-b50c6e0fb16c"
	gw.mu.Unlock()
	code, out := taskExecPost(t, s, token, taskExecBody(decision))
	if code != 403 || out["error"] != "openshell_task_binding_mismatch" {
		t.Fatalf("same-name replacement must reject the old approval: HTTP %d %v", code, out)
	}
	if spy.callCount() != 0 {
		t.Fatal("replaced instance reached the task runner")
	}
	if got := sessionExecHoldStatus(t, s, decision); got != "approved" {
		t.Fatalf("replaced instance must not consume old approval: %q", got)
	}
}

// TestOpenShellTaskExecRefusesMismatchedSubmission proves a submission whose
// params disagree with the approved ones is refused by HTTP without spawning
// anything and without consuming the human approval.
func TestOpenShellTaskExecRefusesMismatchedSubmission(t *testing.T) {
	spy := &taskSpy{}
	s, _ := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)

	for name, mutate := range map[string]func(p map[string]any){
		"argv swapped":      func(p map[string]any) { p["argv"] = []string{"/bin/rm", "-rf", "/"} },
		"target swapped":    func(p map[string]any) { p["target"] = "inst_2" },
		"extra param added": func(p map[string]any) { p["approved_extra"] = true },
		"grant swapped": func(p map[string]any) {
			p["openshell_task"].(map[string]any)["grant_id"] = "grant-other"
		},
	} {
		body := cloneJSON(t, taskExecBody(decision))
		mutate(body["params"].(map[string]any))
		code, out := taskExecPost(t, s, token, body)
		if code != 403 || out["error"] != "openshell_task_binding_mismatch" {
			t.Fatalf("%s: HTTP %d %v", name, code, out)
		}
		if out["task_executed"] != nil {
			t.Fatalf("%s: a refused submission must not claim any execution: %v", name, out)
		}
	}
	if spy.callCount() != 0 {
		t.Fatalf("a mismatched submission must not spawn anything, got %d calls", spy.callCount())
	}
	if got := sessionExecHoldStatus(t, s, decision); got != "approved" {
		t.Fatalf("the approval was consumed by a refused submission: %q", got)
	}
}

// TestOpenShellTaskExecRefusesMismatchedApprovedFields proves the binding covers
// the top-level fields too, not only the params blob.
func TestOpenShellTaskExecRefusesMismatchedApprovedFields(t *testing.T) {
	spy := &taskSpy{}
	s, _ := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)

	for name, mutate := range map[string]func(b map[string]any){
		"argv widened at the top level": func(b map[string]any) { b["argv"] = []string{"/bin/sh", "-c", "curl evil"} },
		"target moved":                  func(b map[string]any) { b["target"] = "inst_2" },
		"policy revision moved":         func(b map[string]any) { b["policy_revision"] = "999" },
		"policy digest moved":           func(b map[string]any) { b["policy_digest"] = strings.Repeat("a", 64) },
		"network target added":          func(b map[string]any) { b["network_targets"] = []string{sessionExecEndpoint, "evil.example:443"} },
		"tool changed":                  func(b map[string]any) { b["tool"] = "write" },
	} {
		body := cloneJSON(t, taskExecBody(decision))
		mutate(body)
		code, out := taskExecPost(t, s, token, body)
		if code != 403 {
			t.Fatalf("%s: HTTP %d %v", name, code, out)
		}
	}
	if spy.callCount() != 0 {
		t.Fatal("no mismatched submission may spawn")
	}
}

// TestOpenShellTaskExecRefusesWhenTheApprovedPolicyMoved proves the last gate
// before reservation: a policy revision or digest that moved after the human
// approved stops the spawn without consuming the approval.
func TestOpenShellTaskExecRefusesWhenTheApprovedPolicyMoved(t *testing.T) {
	spy := &taskSpy{}
	s, gw := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)
	body := taskExecBody(decision)

	// The sandbox's active policy moves on after the approval.
	gw.mu.Lock()
	gw.revision = 2
	gw.body = sessionExecBasePolicy
	gw.mu.Unlock()

	code, out := taskExecPost(t, s, token, body)
	if code != 409 || out["error"] != "openshell_task_policy_not_loaded" {
		t.Fatalf("drifted policy: HTTP %d %v", code, out)
	}
	if spy.callCount() != 0 {
		t.Fatal("the policy gate must run before the spawn")
	}
	if _, exists := out["reservation"]; exists {
		t.Fatalf("a failed load preflight must not reserve: %v", out)
	}
	if got := sessionExecHoldStatus(t, s, decision); got != "approved" {
		t.Fatalf("a failed load preflight consumed approval: %q", got)
	}
}

// TestOpenShellTaskExecSuccessRequiresAZeroExit proves the success path end to
// end, that the command reaches the sandbox as argv, and that the durable
// records carry digests rather than raw text.
func TestOpenShellTaskExecSuccessRequiresAZeroExit(t *testing.T) {
	spy := &taskSpy{}
	s, _ := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)

	code, out := taskExecPost(t, s, token, taskExecBody(decision))
	if code != 200 || out["ok"] != true {
		t.Fatalf("rc=0: HTTP %d %v", code, out)
	}
	if _, present := out["task_executed"]; present {
		t.Fatalf("success must be carried by the signed observation, not a bare flag: %v", out)
	}
	if out["observation_receipt_id"] == nil || out["observation_receipt_id"] == "" {
		t.Fatalf("success must return a signed observation receipt: %v", out)
	}
	if spy.callCount() != 1 {
		t.Fatalf("exactly one spawn, got %d", spy.callCount())
	}

	// The approved command must reach the sandbox as argv after `--`, never as
	// a shell string.
	want := []string{"sandbox", "exec", "-n", taskExecTarget(),
		"--timeout", "60", "--no-tty", "--", "/bin/echo", "siq-task-ok"}
	if got := spy.args[0]; strings.Join(got, "\x00") != strings.Join(want, "\x00") {
		t.Fatalf("argv shape:\n got %q\nwant %q", got, want)
	}
	if spy.limit[0] != openshellTaskDefaultOutputLimit {
		t.Fatalf("output limit: %d", spy.limit[0])
	}
	if spy.timeout[0] != 60*time.Second+15*time.Second {
		t.Fatalf("the local budget must be the approved timeout plus the grace: %s", spy.timeout[0])
	}

	evID := out["binding_evidence_id"].(string)
	ev := readEvidence(t, s, evID)
	if ev["kind"] != "openshell_task_execution_outcome" || ev["task_executed"] != openshell.TaskExecutedYes {
		t.Fatalf("outcome record: %v", ev)
	}
	if ev["argv_count"] != float64(len(taskExecArgv)) || ev["argv_digest"] == "" {
		t.Fatalf("the outcome record must carry the argv digest and count: %v", ev)
	}
	if ev["stdout_bytes"] == float64(0) || ev["stdout_digest"] == "" {
		t.Fatalf("the outcome record must carry the output digest and size: %v", ev)
	}
	for _, forbidden := range taskExecArgv {
		if strings.Contains(mustJSON(t, ev), forbidden) {
			t.Fatalf("evidence must not retain raw command text %q: %v", forbidden, ev)
		}
	}

	// The plan record written BEFORE the spawn is what a restart needs to tell
	// which command a reservation referred to.
	reservation := out["reservation"].(map[string]any)
	plan := readEvidence(t, s, openshellTaskPlanEvidenceID(reservation["reservation_receipt_id"].(string)))
	if plan["kind"] != "openshell_task_execution_plan" {
		t.Fatalf("plan record: %v", plan)
	}
	if plan["argv_digest"] != ev["argv_digest"] || plan["argv_count"] != ev["argv_count"] {
		t.Fatalf("the plan and the outcome must describe the same command: %v vs %v", plan, ev)
	}
	for _, arg := range taskExecArgv {
		if strings.Contains(mustJSON(t, plan), arg) {
			t.Fatalf("the plan must not retain raw argv %q: %v", arg, plan)
		}
	}
}

func mustJSON(t *testing.T, v any) string {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return string(raw)
}

// TestOpenShellTaskExecNonZeroExitStaysUncertain proves a nonzero exit is never
// reported as success, never silently settled, and never replayable.
func TestOpenShellTaskExecNonZeroExitStaysUncertain(t *testing.T) {
	spy := &taskSpy{next: func(int) openshell.TaskRunResult {
		return openshell.TaskRunResult{ExitCode: 7, Stdout: "partial\n", Stderr: "boom\n", Spawned: true}
	}}
	s, _ := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)

	code, out := taskExecPost(t, s, token, taskExecBody(decision))
	if code != 502 || out["error"] != "task_failed" {
		t.Fatalf("rc=7: HTTP %d %v", code, out)
	}
	if out["ok"] != false {
		t.Fatalf("a failed command must never report ok: %v", out)
	}
	if out["execution_uncertain"] != true {
		t.Fatalf("a nonzero exit cannot be told apart from a CLI failure and must stay uncertain: %v", out)
	}
	if _, present := out["reconciliation"]; present {
		t.Fatalf("a spawned-but-failed command must not be auto-reconciled: %v", out)
	}
	reservation := out["reservation"].(map[string]any)
	if got := sessionExecReservationStatus(t, s, decision, reservation); got == "cancelled" {
		t.Fatal("an uncertain execution must not be silently settled")
	}
	outcome := out["outcome"].(map[string]any)
	if outcome["exit_code"] != float64(7) {
		t.Fatalf("the real exit code must be recorded: %v", outcome)
	}
	if outcome["stderr_digest"] == "" || outcome["stderr_bytes"] != float64(len("boom\n")) {
		t.Fatalf("stderr must be recorded as a digest and a size: %v", outcome)
	}
	if strings.Contains(mustJSON(t, out), "boom") {
		t.Fatalf("the response must not echo raw command output: %v", out)
	}

	// Replaying the same approval must be refused, not silently re-executed.
	code, out = taskExecPost(t, s, token, taskExecBody(decision))
	if code < 400 {
		t.Fatalf("a replay of the consumed reservation must fail: HTTP %d %v", code, out)
	}
	if spy.callCount() != 1 {
		t.Fatalf("no replay may reach the runner, got %d calls", spy.callCount())
	}
}

// TestOpenShellTaskExecLocalBoundIsUncertain proves a fired local bound reports
// "we stopped observing", not "the command failed".
func TestOpenShellTaskExecLocalBoundIsUncertain(t *testing.T) {
	for name, bound := range map[string]string{
		"timeout":      openshell.TaskBoundTime,
		"output limit": openshell.TaskBoundOutput,
		"pipe timeout": openshell.TaskBoundPipe,
	} {
		spy := &taskSpy{next: func(int) openshell.TaskRunResult {
			return openshell.TaskRunResult{ExitCode: -1, BoundFired: bound, Spawned: true}
		}}
		s, _ := newTaskExecServer(t, spy)
		decision := taskExecApproveHold(t, s)
		code, out := taskExecPost(t, s, token, taskExecBody(decision))
		if code != 502 || out["error"] != "execution_uncertain" {
			t.Fatalf("%s: HTTP %d %v", name, code, out)
		}
		if out["execution_uncertain"] != true {
			t.Fatalf("%s: a local bound means the sandbox command may still run: %v", name, out)
		}
		if _, present := out["reconciliation"]; present {
			t.Fatalf("%s: an uncertain outcome must not auto-reconcile: %v", name, out)
		}
	}
}

// TestOpenShellTaskExecEvidenceFailureNeverReportsSuccess proves the
// result-storage rule: when the durable record cannot be written, a command
// that really ran is reported as executed-but-unrecorded.
func TestOpenShellTaskExecEvidenceFailureNeverReportsSuccess(t *testing.T) {
	spy := &taskSpy{}
	s, _ := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)
	evDir := filepath.Join(s.d.Store.Dir, "evidence")
	if _, err := os.Stat(evDir); err != nil {
		t.Fatalf("the evidence directory must exist after approval: %v", err)
	}
	// The plan record is already written. As a side effect of the spawn — that
	// is, after the plan and before the outcome — make every later evidence
	// write fail.
	spy.next = func(int) openshell.TaskRunResult {
		if err := os.Chmod(evDir, 0o500); err != nil {
			t.Errorf("chmod evidence dir: %v", err)
		}
		return openshell.TaskRunResult{ExitCode: 0, Stdout: "ok\n", Spawned: true}
	}
	defer func() { _ = os.Chmod(evDir, 0o700) }()

	code, out := taskExecPost(t, s, token, taskExecBody(decision))
	if code != 503 || out["error"] != "execution_evidence_incomplete" {
		t.Fatalf("unrecorded execution: HTTP %d %v", code, out)
	}
	if out["task_executed"] != openshell.TaskExecutedYes {
		t.Fatalf("it really ran and must be reported as executed: %v", out)
	}
	if out["ok"] != false {
		t.Fatalf("an unrecorded execution must not report ok: %v", out)
	}
	if spy.callCount() != 1 {
		t.Fatalf("the command ran exactly once, got %d", spy.callCount())
	}
}

// A nonzero exit or local bound already carries an unresolved reservation.
// Losing its result record must also be visible in the response: the ordinary
// 502 alone would hide the separate persistence failure from the operator.
func TestOpenShellTaskExecUncertainEvidenceFailureIsExplicit(t *testing.T) {
	for name, result := range map[string]openshell.TaskRunResult{
		"nonzero exit":  {ExitCode: 7, Stderr: "private-failure-output", Spawned: true},
		"local timeout": {ExitCode: -1, BoundFired: openshell.TaskBoundTime, Spawned: true},
	} {
		t.Run(name, func(t *testing.T) {
			spy := &taskSpy{}
			s, _ := newTaskExecServer(t, spy)
			decision := taskExecApproveHold(t, s)
			evDir := filepath.Join(s.d.Store.Dir, "evidence")
			spy.next = func(int) openshell.TaskRunResult {
				if err := os.Chmod(evDir, 0o500); err != nil {
					t.Errorf("chmod evidence dir: %v", err)
				}
				return result
			}
			defer func() { _ = os.Chmod(evDir, 0o700) }()

			code, out := taskExecPost(t, s, token, taskExecBody(decision))
			if code != 503 || out["error"] != "execution_evidence_incomplete" || out["reason_code"] != "execution_evidence_incomplete" {
				t.Fatalf("unrecorded %s: HTTP %d %v", name, code, out)
			}
			if out["binding_evidence_persisted"] != false || out["task_executed"] != openshell.TaskExecutedUnknown || out["execution_uncertain"] != true {
				t.Fatalf("the command may have run but its outcome was not durable: %v", out)
			}
			if _, present := out["reconciliation"]; present {
				t.Fatalf("a spawned task must not auto-reconcile: %v", out)
			}
			if spy.callCount() != 1 {
				t.Fatalf("expected one execution, got %d", spy.callCount())
			}
			if strings.Contains(mustJSON(t, out), "private-failure-output") {
				t.Fatalf("raw output leaked in response: %v", out)
			}
		})
	}
}

func TestOpenShellTaskExecAuditFailureIsExplicit(t *testing.T) {
	spy := &taskSpy{next: func(int) openshell.TaskRunResult {
		return openshell.TaskRunResult{ExitCode: 7, Stderr: "private-audit-failure", Spawned: true}
	}}
	s, _ := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)
	auditPath := filepath.Join(s.d.Store.Dir, "audit.jsonl")
	if _, err := os.Stat(auditPath); err != nil {
		t.Fatalf("expected existing audit log: %v", err)
	}
	if err := os.Chmod(auditPath, 0o400); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = os.Chmod(auditPath, 0o600) }()

	code, out := taskExecPost(t, s, token, taskExecBody(decision))
	if code != 503 || out["error"] != "execution_evidence_incomplete" {
		t.Fatalf("unrecorded audit: HTTP %d %v", code, out)
	}
	if out["binding_evidence_persisted"] != true || out["task_executed"] != openshell.TaskExecutedUnknown || out["execution_uncertain"] != true {
		t.Fatalf("the result record is durable but its audit is not: %v", out)
	}
	if spy.callCount() != 1 || strings.Contains(mustJSON(t, out), "private-audit-failure") {
		t.Fatalf("must execute once without leaking output: %v", out)
	}
}

// TestOpenShellTaskExecPlanNotPersistedRefusesBeforeSpawn covers the one branch
// that the evidence-failure test above cannot reach, because that chmod happens
// inside the spawn and the plan is written before the spawn.
//
// The reservation receipts carry only a params digest, so a plan record that
// cannot be written means a restart could not say which command a consumed
// reservation referred to. The handler must therefore refuse to spawn at all --
// not run and hope the outcome write succeeds.
func TestOpenShellTaskExecPlanNotPersistedRefusesBeforeSpawn(t *testing.T) {
	spy := &taskSpy{}
	s, _ := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)
	evDir := filepath.Join(s.d.Store.Dir, "evidence")
	if _, err := os.Stat(evDir); err != nil {
		t.Fatalf("the evidence directory must exist after approval: %v", err)
	}
	// Blocked before the request: the reservation still has to succeed (it is
	// durable in the signed chain, not here), and the plan write is the first
	// thing that needs this directory.
	if err := os.Chmod(evDir, 0o500); err != nil {
		t.Fatalf("chmod evidence dir: %v", err)
	}
	defer func() { _ = os.Chmod(evDir, 0o700) }()

	code, out := taskExecPost(t, s, token, taskExecBody(decision))
	if code != 503 || out["error"] != "task_plan_not_persisted" {
		t.Fatalf("unpersisted plan: HTTP %d %v", code, out)
	}
	if out["task_executed"] != false {
		t.Fatalf("nothing may run when the plan is not durable: %v", out)
	}
	if out["execution_uncertain"] != false {
		t.Fatalf("nothing was spawned, so the outcome is not uncertain: %v", out)
	}
	if spy.callCount() != 0 {
		t.Fatalf("the executor ran %d times without a durable plan", spy.callCount())
	}
	// The reservation was consumed before the failure, so the response must say
	// so and must carry the signed reconciliation that closed it -- otherwise a
	// caller sees an approval that vanished with no finding to point at.
	reserved, _ := out["reservation"].(map[string]any)
	if reserved == nil || reserved["reservation_receipt_id"] == "" {
		t.Fatalf("the reservation must have been consumed and reported: %v", out)
	}
	recon, _ := out["reconciliation"].(map[string]any)
	if recon == nil {
		t.Fatalf("a consumed reservation with no durable plan must be reconciled: %v", out)
	}
	if recon["reconciliation_receipt_id"] == nil || recon["reconciliation_receipt_id"] == "" {
		t.Fatalf("the reconciliation must be a signed receipt, not an in-memory note: %v", recon)
	}
	if recon["reason_code"] != "hold_execution_confirmed_not_occurred" {
		t.Fatalf("the finding must be not_occurred, since nothing was spawned: %v", recon)
	}
	if recon["reservation_receipt_id"] != reserved["reservation_receipt_id"] {
		t.Fatalf("the reconciliation must close the reservation that was actually consumed: %v", recon)
	}
}

// TestOpenShellTaskExecPreviewIsAdvisoryOnly proves the preview route never
// executes, never consumes a reservation, and never claims verification.
func TestOpenShellTaskExecPreviewIsAdvisoryOnly(t *testing.T) {
	spy := &taskSpy{}
	s, _ := newTaskExecServer(t, spy)
	const path = "/v1/openshell/task-executions/preview"

	if code, _ := sessionExecPost(t, s, path, "", map[string]any{"target": taskExecTarget()}); code != 401 {
		t.Fatalf("preview must require a credential: HTTP %d", code)
	}
	if code, _ := sessionExecPost(t, s, path, s.bootAdmin, map[string]any{}); code != 400 {
		t.Fatalf("preview must require a target: HTTP %d", code)
	}
	code, out := sessionExecPost(t, s, path, s.bootAdmin, map[string]any{"target": "inst-unknown"})
	if code != 403 || out["error"] != "target_not_authorized" {
		t.Fatalf("unauthorized target: HTTP %d %v", code, out)
	}
	code, out = sessionExecPost(t, s, path, s.bootAdmin, map[string]any{"target": taskExecTarget()})
	if code != 200 {
		t.Fatalf("preview: HTTP %d %v", code, out)
	}
	if out["mode"] != "advisory" || out["task_executed"] != false || out["execution_constraints_verified"] != false {
		t.Fatalf("preview must not claim execution or verification: %v", out)
	}
	if out["scope"] != "task_execution" {
		t.Fatalf("preview must declare the task scope, not the policy scope: %v", out)
	}
	live, _ := out["live"].(map[string]any)
	if live == nil || live["sandbox_id"] != "de99ab6a-8e47-487d-8f69-6e5b6ae9c7a2" {
		t.Fatalf("preview must expose the current advisory sandbox identity: %v", out)
	}
	if spy.callCount() != 0 {
		t.Fatal("preview must never spawn")
	}
}
