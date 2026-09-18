package server

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net"
	"strconv"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/openshell"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

// Task-command binding.
//
// The submitted fields are requests only. This file rebuilds the ENTIRE final
// plan server-side from signed state plus the approved parameters and then
// requires byte equality with the parameters the human actually approved, so
// approving one command can never execute a different one.
//
// Two independent binds must both hold:
//   - the engine's reservation contract digests req.Params and matches it to
//     the decision (ReserveHoldExecution / RecheckReservedExecution);
//   - this file binds those same params to the signed decision, the current
//     grant, the backend fingerprint and the network scope.
//
// Neither alone is sufficient: the engine proves "the approver approved THESE
// params", this file proves "THESE params mean THIS command against THIS
// backend and THIS authorization".

// openshellTaskCommand is the canonical command name bound into the approved
// params. A task execution request that does not carry exactly this command
// name is not an approval for this operation.
const openshellTaskCommand = "siq-openshell-task-exec"

// openshellTaskSchemaRequest is the PUBLIC schema of this route, as declared by
// packages/contracts/openshell-task-execution-request.v1.schema.json. The
// embedded reservation sub-object that the engine validates carries its own
// schema constant (openshellExecSchemaReserve); the handler translates one into
// the other at the single point where the reservation is created, so the
// public contract and the engine contract can each stay truthful.
const openshellTaskSchemaRequest = "openshell-task-execution-request/v1"

// Task execution defaults, applied identically when the plan is rebuilt and
// when it is submitted, so an omitted field cannot change the meaning of an
// approval.
const (
	openshellTaskDefaultTimeoutSeconds = 60
	openshellTaskDefaultOutputLimit    = 64 << 10
)

func (t openshellTaskExecuteRequest) effectiveTimeoutSeconds() int {
	if t.TimeoutSeconds <= 0 {
		return openshellTaskDefaultTimeoutSeconds
	}
	return t.TimeoutSeconds
}

func (t openshellTaskExecuteRequest) effectiveOutputLimit() int {
	if t.OutputLimit <= 0 {
		return openshellTaskDefaultOutputLimit
	}
	return t.OutputLimit
}

// canonicalTaskParams rebuilds the approved parameter object from the request
// and signed state. Both the submitter and this validator must produce exactly
// this structure; anything else is a binding mismatch and is refused.
func canonicalTaskParams(body openshellTaskExecuteRequest, g *grant.Grant, grantDigest, fingerprint, sandboxID string) map[string]any {
	urls := make([]string, len(body.NetworkTargets))
	for i, ep := range body.NetworkTargets {
		urls[i] = "https://" + ep
	}
	return map[string]any{
		"command": openshellTaskCommand,
		"target":  body.Target,
		// The argv is present because the human approves the exact command;
		// it is never copied into an evidence or observation record, which
		// carry only its digest and element count.
		"argv":               body.Argv,
		"workdir":            body.Workdir,
		"timeout_seconds":    body.effectiveTimeoutSeconds(),
		"output_limit_bytes": body.effectiveOutputLimit(),
		"policy_revision":    body.PolicyRevision,
		"policy_digest":      body.PolicyDigest,
		"authorization_urls": urls,
		// Only values the approver can know BEFORE the decision exists are bound
		// here. decision_receipt_id / action_id / tool-call ids are produced by
		// the decision itself, so requiring them in the approved params would
		// make every submission unapprovable. They are not left unbound: the
		// engine's reserveMatchesDecision already binds all four against the
		// signed decision record, and validateOpenShellTaskExecutionBinding
		// looks that exact decision up by id.
		"openshell_task": map[string]any{
			"target": body.Target, "grant_id": g.GrantID, "grant_digest": grantDigest,
			"endpoint_fingerprint": fingerprint, "sandbox_id": sandboxID,
		},
	}
}

// validateOpenShellTaskExecutionBinding is the only place that decides a task
// submission matches its approval. It re-reads the signed chain and the grant
// store on every call, so it is also safe to use as the pre-spawn recheck.
func (s *Server) validateOpenShellTaskExecutionBinding(body openshellTaskExecuteRequest) (*grant.Grant, error) {
	if body.Target != body.AgentID || body.Tool != "exec" {
		return nil, fmt.Errorf("openshell_task_binding_mismatch")
	}
	// Refuse a changed requested revision as a binding error before querying
	// the gateway. Otherwise a different revision can look like an unavailable
	// instance and obscure the actual approved-parameter mismatch.
	if body.Params["policy_revision"] != body.PolicyRevision {
		return nil, fmt.Errorf("openshell_task_binding_mismatch")
	}
	chain, err := s.d.Chain.Read()
	if err != nil || receipt.Verify(chain, s.d.Key.Public()) != nil {
		return nil, fmt.Errorf("openshell_chain_unverified")
	}
	var decision *receipt.Receipt
	for i := range chain {
		if chain[i].ReceiptID == body.DecisionReceiptID && chain[i].RecordType == "decision" {
			decision = &chain[i]
			break
		}
	}
	if decision == nil || decision.MatchedGrantID == nil {
		return nil, fmt.Errorf("openshell_decision_missing")
	}
	g, err := s.d.Store.GetGrant(*decision.MatchedGrantID)
	if err != nil || g == nil || !grant.Verify(s.d.Key.Public(), *g) || grant.ValidateLifetime(*g, time.Now()) != nil ||
		(g.Status != "deployed" && g.Status != "effective") || g.Platform != body.Platform || g.Subject.ID != body.AgentID {
		return nil, fmt.Errorf("openshell_grant_invalid")
	}
	digest, err := grant.PermissionDigest(*g)
	if err != nil {
		return nil, fmt.Errorf("openshell_grant_invalid")
	}
	fingerprint := s.d.Openshell.InvocationFingerprint()
	if fingerprint == "" {
		return nil, fmt.Errorf("openshell_backend_unbound")
	}
	sandboxID, err := s.d.Openshell.CurrentTaskSandboxID(body.Target, body.PolicyRevision)
	if err != nil {
		return nil, fmt.Errorf("openshell_task_instance_unconfirmed")
	}
	expected, err := json.Marshal(canonicalTaskParams(body, g, digest, fingerprint, sandboxID))
	if err != nil {
		return nil, err
	}
	actual, err := json.Marshal(body.Params)
	if err != nil || !bytes.Equal(expected, actual) {
		return nil, fmt.Errorf("openshell_task_binding_mismatch")
	}
	allowed := grantNetwork(*g)
	for _, ep := range body.NetworkTargets {
		if !allowed[ep] {
			return nil, fmt.Errorf("endpoint_not_authorized")
		}
	}
	return g, nil
}

// validTaskEndpoint mirrors the contract's canonical host:port shape. It
// refuses anything a shell, a URL parser or a proxy could re-interpret.
func validTaskEndpoint(ep string) bool {
	host, port, err := net.SplitHostPort(ep)
	n, e := strconv.Atoi(port)
	if err != nil || e != nil || host == "" || len(host) > 253 || n < 1 || n > 65535 || strconv.Itoa(n) != port {
		return false
	}
	return !strings.ContainsAny(host, "/?#@ \t\r\n")
}

func validTaskWorkdirShape(dir string) bool {
	if dir == "" {
		return true
	}
	if len(dir) > 1024 || dir[0] != '/' {
		return false
	}
	if strings.ContainsFunc(dir, func(r rune) bool { return r < 0x20 || r == 0x7f }) {
		return false
	}
	for _, part := range strings.Split(dir, "/") {
		if part == ".." {
			return false
		}
	}
	return true
}

// validOpenShellTaskShape is the fail-closed shape gate that runs BEFORE any
// authorization is consumed, so a malformed submission never burns the human
// approval. It deliberately duplicates the executor's own validation: the
// cheap refusal belongs at the edge, the authoritative one stays with the
// code that spawns the process.
func validOpenShellTaskShape(body openshellTaskExecuteRequest) bool {
	if body.SchemaVersion != openshellTaskSchemaRequest {
		return false
	}
	// An empty network_targets list is allowed: a task that needs no declared
	// network scope must not be refused by a gate stricter than the contract.
	// A NON-empty list still has to be covered by the grant, below.
	if body.Target == "" || len(body.Argv) == 0 || len(body.Argv) > 256 || len(body.NetworkTargets) > 64 {
		return false
	}
	for _, a := range body.Argv {
		if a == "" || len(a) > 4096 || strings.ContainsRune(a, 0) {
			return false
		}
	}
	if !validTaskWorkdirShape(body.Workdir) {
		return false
	}
	// Constant false in the contract: raw output is never retained on this path.
	if body.StoreRawOutput != nil && *body.StoreRawOutput {
		return false
	}
	if body.TimeoutSeconds < 0 || body.TimeoutSeconds > 900 {
		return false
	}
	if body.OutputLimit < 0 || body.OutputLimit > 1048576 || (body.OutputLimit > 0 && body.OutputLimit < 4096) {
		return false
	}
	if !canonicalRevision(body.PolicyRevision) || len(body.PolicyDigest) != 64 {
		return false
	}
	for _, r := range body.PolicyDigest {
		if (r < '0' || r > '9') && (r < 'a' || r > 'f') {
			return false
		}
	}
	for _, ep := range body.NetworkTargets {
		if !validTaskEndpoint(ep) {
			return false
		}
	}
	return true
}

// bindTaskExecRequest converts an approved submission into the executor's
// request. Every value is re-derived here from validated fields; nothing is
// passed through because it merely arrived.
//
// reservationReceiptID becomes the execution key. It is a handle, not a
// credential: it is derived from the reservation this call just created, and it
// only ever lets a later stop request reach this one local process.
func bindTaskExecRequest(body openshellTaskExecuteRequest, reservationReceiptID string) openshell.TaskExecRequest {
	return openshell.TaskExecRequest{
		ExecutionKey:   reservationReceiptID,
		Target:         body.Target,
		Argv:           append([]string(nil), body.Argv...),
		NetworkTargets: append([]string(nil), body.NetworkTargets...),
		Workdir:        body.Workdir,
		TimeoutSeconds: body.effectiveTimeoutSeconds(),
		OutputLimit:    body.effectiveOutputLimit(),
		PolicyRevision: body.PolicyRevision,
		PolicyDigest:   body.PolicyDigest,
	}
}
