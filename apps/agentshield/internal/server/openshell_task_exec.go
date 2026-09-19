package server

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"sort"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/openshell"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/state"
)

// Real OpenShell task execution. This file adds EXECUTION, it adds no
// authority: the hold decision plane stays the only source of permission, the
// signed chain stays the only durable record, and grants stay the only source
// of network scope. It consumes the same single reservation as the
// policy-apply route and reuses the same engine contracts.
//
// Deliberately NOT shared with the policy-apply route: policy apply writes
// gateway policy and can be rolled back from an owned operation handle; a task
// command has no rollback and its outcome is only ever the command's own exit
// status. Conflating the two is exactly the "silently upgrade an old request
// into real command execution" failure this batch must avoid.
//
// Outcome honesty:
//   - rc == 0 proves the remote command ran and succeeded.
//   - Any other rc proves only "did not succeed": a nonzero remote exit and a
//     CLI-side failure are indistinguishable, so it is reported
//     task_executed=unknown, execution_uncertain, never auto-reconciled and
//     never replayed.
//   - A local bound firing (timeout / output limit / pipe) means WE stopped
//     observing; the remote may still be running. Uncertain.
//   - Only a preflight refusal spawns nothing, so only it is provably
//     not_occurred and may auto-reconcile.

// openshellTaskExecuteRequest mirrors
// packages/contracts/openshell-task-execution-request.v1.schema.json field for
// field; readJSONStrict rejects anything else, so a contract change is a
// compile-or-400 failure rather than a silently ignored field.
type openshellTaskExecuteRequest struct {
	receipt.HoldExecutionReserve
	Target         string   `json:"target"`
	Argv           []string `json:"argv"`
	Workdir        string   `json:"workdir,omitempty"`
	TimeoutSeconds int      `json:"timeout_seconds,omitempty"`
	OutputLimit    int      `json:"output_limit_bytes,omitempty"`
	PolicyRevision string   `json:"policy_revision"`
	PolicyDigest   string   `json:"policy_digest"`
	NetworkTargets []string `json:"network_targets"`
	// Constant false in the contract; a pointer so an explicit true is
	// distinguishable from an omitted field and can be refused.
	StoreRawOutput *bool `json:"store_raw_output,omitempty"`
}

func openshellTaskEvidenceID(reservationReceiptID string) string {
	sum := sha256.Sum256([]byte("ost|" + reservationReceiptID))
	return "ost-" + hex.EncodeToString(sum[:8])
}

func openshellTaskPlanEvidenceID(reservationReceiptID string) string {
	sum := sha256.Sum256([]byte("ostp|" + reservationReceiptID))
	return "ostp-" + hex.EncodeToString(sum[:8])
}

// openshellTaskStartEvidenceID names the durable launch marker. It is a third
// id rather than a flag inside the plan record because the plan is written
// before the start and evidence files are immutable: the two facts are created
// at different moments and a crash between them must remain visible.
func openshellTaskStartEvidenceID(reservationReceiptID string) string {
	sum := sha256.Sum256([]byte("ostart|" + reservationReceiptID))
	return "ostart-" + hex.EncodeToString(sum[:8])
}

// argvDigest is the only representation of the command that reaches a durable
// record. The raw argv lives in the approved params (the human approves the
// exact command) and is never copied into evidence, observations or audits.
func argvDigest(argv []string) string {
	blob, err := json.Marshal(argv)
	if err != nil {
		return ""
	}
	sum := sha256.Sum256(blob)
	return hex.EncodeToString(sum[:])
}

func (s *Server) taskActorID(body openshellTaskExecuteRequest) string {
	if id := strings.TrimSpace(body.AgentID); id != "" {
		return id
	}
	return "openshell-task-executor"
}

// persistTaskPlan writes the durable non-process-local plan record. Reservation
// receipts in the signed chain carry only a params digest, so without this a
// restart could not say which command a reservation referred to.
func (s *Server) persistTaskPlan(reserveStatus *receipt.HoldExecutionStatus, body openshellTaskExecuteRequest, actorID string) bool {
	evID := openshellTaskPlanEvidenceID(reserveStatus.ReservationReceiptID)
	doc := map[string]any{
		"kind":                   "openshell_task_execution_plan",
		"reservation_receipt_id": reserveStatus.ReservationReceiptID,
		"action_id":              reserveStatus.ActionID,
		"decision_receipt_id":    reserveStatus.DecisionReceiptID,
		"actor_id":               actorID,
		"target":                 body.Target,
		"argv_digest":            argvDigest(body.Argv),
		"argv_count":             len(body.Argv),
		"workdir":                body.Workdir,
		"timeout_seconds":        body.effectiveTimeoutSeconds(),
		"output_limit_bytes":     body.effectiveOutputLimit(),
		"policy_revision":        body.PolicyRevision,
		"policy_digest":          body.PolicyDigest,
		"network_targets":        body.NetworkTargets,
		// The reservation's own deadline, recorded so a later read-only
		// projection can tell an expired reservation from a live one without
		// re-deriving it from process state.
		"reservation_expires_at": reserveStatus.ExpiresAt,
		"recorded_at":            time.Now().UTC().Format(time.RFC3339),
	}
	return s.signTaskEvidence(doc) == nil && s.d.Store.PutEvidence(evID, doc) == nil
}

// persistTaskStart writes the durable launch marker. It is the boundary between
// "reserved but never launched" and "launch was attempted": a restart that finds
// the plan record but no start marker can honestly report reserved, while a
// restart that finds the start marker must not claim the task never ran.
//
// Like the plan record it is written BEFORE the spawn, so a crash can only ever
// lose the fact that the launch would have been attempted, never invent one.
func (s *Server) persistTaskStart(reserveStatus *receipt.HoldExecutionStatus, body openshellTaskExecuteRequest, actorID string) bool {
	doc := map[string]any{
		"kind":                   "openshell_task_execution_start",
		"reservation_receipt_id": reserveStatus.ReservationReceiptID,
		"action_id":              reserveStatus.ActionID,
		"decision_receipt_id":    reserveStatus.DecisionReceiptID,
		"actor_id":               actorID,
		"target":                 body.Target,
		"argv_digest":            argvDigest(body.Argv),
		"argv_count":             len(body.Argv),
		"policy_revision":        body.PolicyRevision,
		"policy_digest":          body.PolicyDigest,
		"recorded_at":            time.Now().UTC().Format(time.RFC3339),
	}
	return s.signTaskEvidence(doc) == nil && s.d.Store.PutEvidence(openshellTaskStartEvidenceID(reserveStatus.ReservationReceiptID), doc) == nil
}

// taskOutcomeDoc is the durable record of what actually happened. It stores
// digests and counts, never raw output and never raw argv.
func taskOutcomeDoc(reserveStatus *receipt.HoldExecutionStatus, body openshellTaskExecuteRequest, actorID string, outcome openshell.TaskExecOutcome) map[string]any {
	return map[string]any{
		"kind":                   "openshell_task_execution_outcome",
		"reservation_receipt_id": reserveStatus.ReservationReceiptID,
		"action_id":              reserveStatus.ActionID,
		"decision_receipt_id":    reserveStatus.DecisionReceiptID,
		"actor_id":               actorID,
		"target":                 body.Target,
		"argv_digest":            argvDigest(body.Argv),
		"argv_count":             len(body.Argv),
		"state":                  outcome.State,
		"task_executed":          outcome.TaskExecuted,
		"execution_uncertain":    outcome.ExecutionUncertain,
		"spawned":                outcome.Spawned,
		"preflight_refused":      outcome.PreflightRefused,
		"refusal":                outcome.Refusal,
		"bound_fired":            outcome.BoundFired,
		"exit_code":              outcome.ExitCode,
		"exit_code_attribution":  outcome.ExitCodeAttribution,
		"foreign_backend":        outcome.ForeignBackend,
		"stdout_digest":          outcome.StdoutDigest,
		"stdout_bytes":           outcome.StdoutBytes,
		"stderr_digest":          outcome.StderrDigest,
		"stderr_bytes":           outcome.StderrBytes,
		"started_at":             outcome.StartedAt,
		"finished_at":            outcome.FinishedAt,
		"policy_revision":        outcome.PolicyRevision,
		"policy_digest":          outcome.PolicyDigest,
	}
}

func (s *Server) appendTaskAudit(event, target, note string) error {
	return s.d.Store.AppendAudit(state.AuditEvent{
		At: time.Now().UTC().Format(time.RFC3339), Event: event, Target: target, Note: note,
	})
}

func (s *Server) openshellTaskExecute(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST required"})
		return
	}
	var body openshellTaskExecuteRequest
	// Larger than the policy route: 256 argv elements at up to 4096 bytes each
	// is roughly 1 MiB before JSON overhead.
	if err := readJSONStrict(r, &body, 2<<21); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	if !validOpenShellTaskShape(body) {
		writeJSON(w, 400, map[string]string{"error": "invalid_openshell_task_shape", "reason_code": "invalid_openshell_task_shape"})
		return
	}
	if !s.openshellExecL3Gate(w) {
		return
	}
	// Every authorization pre-check runs before the reservation is consumed,
	// so a rejected submission never burns the human approval.
	if _, err := s.validateOpenShellTaskExecutionBinding(body); err != nil {
		code := http.StatusForbidden
		if err.Error() == "openshell_task_instance_unconfirmed" {
			code = http.StatusConflict
		}
		writeJSON(w, code, map[string]string{"error": err.Error(), "reason_code": err.Error()})
		return
	}
	// A matching policy readback alone is not a load acknowledgement. Check
	// the bound endpoint's in-process set --wait proof before spending the
	// one-use hold; ExecTask repeats this under the target lock before spawn.
	if err := s.d.Openshell.VerifyTaskPolicyLoaded(body.Target, body.PolicyRevision, body.PolicyDigest, body.NetworkTargets); err != nil {
		writeJSON(w, http.StatusConflict, map[string]string{"error": err.Error(), "reason_code": err.Error()})
		return
	}
	// The shape gate accepted the PUBLIC contract version. The engine's
	// reservation contract validates its own schema constant, and the approved
	// params were just verified against the submitted bytes, so this single
	// translation is the only difference between what the client sent and what
	// the reservation record carries.
	body.HoldExecutionReserve.SchemaVersion = openshellExecSchemaReserve
	reserveStatus, err := s.d.Engine.ReserveHoldExecution(body.HoldExecutionReserve)
	if err != nil {
		code := http.StatusBadRequest
		switch {
		case errors.Is(err, receipt.ErrHoldExecutionConflict):
			code = http.StatusConflict
		case errors.Is(err, receipt.ErrHoldExpired):
			code = http.StatusGone
		}
		reason := err.Error()
		var correlation *receipt.CorrelationError
		if errors.As(err, &correlation) {
			reason = correlation.Code
		}
		writeJSON(w, code, map[string]string{"error": reason, "reason_code": reason})
		return
	}
	actorID := s.taskActorID(body)
	// The reservation is durable in the signed chain; the plan record must be
	// too, BEFORE any external side effect, or a later restart could not tell
	// what this reservation referred to.
	if !s.persistTaskPlan(reserveStatus, body, actorID) {
		recStatus, recErr := s.reconcileUncertainExecution(reserveStatus, actorID, receipt.HoldExecutionNotOccurred)
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"ok": false, "error": "task_plan_not_persisted", "reason_code": "task_plan_not_persisted",
			"scope": "task_execution", "task_executed": false, "execution_uncertain": false,
			"reservation": reserveStatus, "reconciliation": recStatus, "note": reconcileNote(recErr),
		})
		return
	}
	// Second durable marker, still before the spawn: a restart that finds the
	// plan but not this marker must report "reserved, never launched" rather
	// than guess. Nothing has been spawned at this point, so refusing here is
	// the same provably-not-occurred case as the plan write failing.
	if !s.persistTaskStart(reserveStatus, body, actorID) {
		recStatus, recErr := s.reconcileUncertainExecution(reserveStatus, actorID, receipt.HoldExecutionNotOccurred)
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"ok": false, "error": "task_start_not_persisted", "reason_code": "task_start_not_persisted",
			"scope": "task_execution", "task_executed": false, "execution_uncertain": false,
			"reservation": reserveStatus, "reconciliation": recStatus, "note": reconcileNote(recErr),
		})
		return
	}
	// Re-checked immediately before the spawn: the binding against signed
	// state and the reservation's own revocation/session contract.
	outcome, _ := s.d.Openshell.ExecTask(bindTaskExecRequest(body, reserveStatus.ReservationReceiptID), func() error {
		if _, err := s.validateOpenShellTaskExecutionBinding(body); err != nil {
			return err
		}
		return s.d.Engine.RecheckReservedExecution(receipt.HoldExecutionStatusRequest{
			SchemaVersion: "hold-execution-status-request/v1", Platform: body.Platform, SessionID: body.SessionID, AgentID: body.AgentID,
			TaskID: body.TaskID, RuntimeTaskID: body.RuntimeTaskID, Tool: body.Tool, RetryToolCallID: body.RetryToolCallID,
			ActionID: body.ActionID, DecisionReceiptID: body.DecisionReceiptID, ReservationReceiptID: reserveStatus.ReservationReceiptID, Params: body.Params,
		})
	})
	evID := openshellTaskEvidenceID(reserveStatus.ReservationReceiptID)
	doc := taskOutcomeDoc(reserveStatus, body, actorID, outcome)
	persisted := s.signTaskEvidence(doc) == nil && s.d.Store.PutEvidence(evID, doc) == nil
	auditErr := s.appendTaskAudit("openshell_task_execution", body.Target,
		"reservation="+reserveStatus.ReservationReceiptID+" state="+outcome.State+" spawned="+boolWord(outcome.Spawned))

	base := map[string]any{
		"scope": "task_execution", "reservation": reserveStatus, "outcome": outcome,
		"target": body.Target, "binding_evidence_id": evID, "binding_evidence_persisted": persisted,
	}
	// Once a child was spawned, the result record and audit are part of the
	// evidence needed to explain the consumed reservation after a restart.
	// A failed/limited command is no exception: returning its ordinary error
	// would conceal that this separate durability guarantee was lost.
	if outcome.Spawned && (!persisted || auditErr != nil) {
		base["ok"] = false
		base["error"] = "execution_evidence_incomplete"
		base["reason_code"] = "execution_evidence_incomplete"
		base["task_executed"] = outcome.TaskExecuted
		base["execution_uncertain"] = outcome.TaskExecuted != openshell.TaskExecutedYes
		writeJSON(w, http.StatusServiceUnavailable, base)
		return
	}
	switch outcome.State {
	case openshell.TaskStateSucceeded:
		summary, _ := json.Marshal(doc)
		obs, obsErr := s.d.Engine.Observe(receipt.Request{
			Platform: body.Platform,
			TaskID:   body.TaskID, RuntimeTaskID: body.RuntimeTaskID,
			SessionID:         body.SessionID,
			AgentID:           body.AgentID,
			Tool:              body.Tool,
			ToolCallID:        body.RetryToolCallID,
			ActionID:          body.ActionID,
			DecisionReceiptID: reserveStatus.ReservationReceiptID,
			Params:            body.Params,
		}, string(summary))
		if obsErr != nil {
			base["ok"] = false
			base["task_executed"] = openshell.TaskExecutedYes
			base["observation_error"] = sanitizeOpenshellErr(obsErr)
			writeJSON(w, http.StatusServiceUnavailable, base)
			return
		}
		base["ok"] = true
		base["observation_receipt_id"] = obs.ReceiptID
		writeJSON(w, http.StatusOK, base)
	case openshell.TaskStateRefused:
		// Provably nothing was spawned, so this may auto-reconcile.
		recStatus, recErr := s.reconcileUncertainExecution(reserveStatus, actorID, receipt.HoldExecutionNotOccurred)
		base["ok"] = false
		base["error"] = "execution_refused"
		base["reason_code"] = "execution_refused"
		base["execution"] = receipt.HoldExecutionNotOccurred
		base["reconciliation"] = recStatus
		base["note"] = reconcileNote(recErr)
		writeJSON(w, http.StatusConflict, base)
	case openshell.TaskStateStopped:
		// A stop was requested while we were observing. Only ONE sub-case is
		// provable: the stop arrived before the child existed, so nothing was
		// started here and the reservation may be closed as not-occurred.
		//
		// A stop that arrived after the spawn is NOT provable in the same sense.
		// SIQ has no verified remote stop path, so all we know is what we asked our own
		// process to do; the sandbox may still be running the command. That case
		// must not be reported as a clean stop and must not be auto-reconciled —
		// it stays uncertain for the administrator, exactly like a fired local
		// bound.
		if outcome.Spawned || outcome.Refusal != openshell.TaskRefusalStopBeforeSpawn {
			base["ok"] = false
			base["error"] = "execution_uncertain"
			base["reason_code"] = "execution_stopped_after_spawn_uncertain"
			base["execution_uncertain"] = true
			base["note"] = "本地已发起命令并收到停止请求；SIQ 当前未接入远端停止确认，远端可能仍在运行，预留保持未决等待管理员对账，不会自动重放"
			writeJSON(w, http.StatusBadGateway, base)
			return
		}
		recStatus, recErr := s.reconcileUncertainExecution(reserveStatus, actorID, receipt.HoldExecutionNotOccurred)
		base["ok"] = false
		base["error"] = "execution_stopped_before_spawn"
		base["reason_code"] = "execution_stopped_before_spawn"
		base["execution"] = receipt.HoldExecutionNotOccurred
		base["reconciliation"] = recStatus
		base["note"] = "停止请求在子进程启动前到达，本进程未发起任何命令；" + reconcileNote(recErr)
		writeJSON(w, http.StatusConflict, base)
	case openshell.TaskStateFailed:
		// Did not succeed; whether it ran is unknowable from here.
		//
		// execution_uncertain is true here even when the client outcome's own
		// ExecutionUncertain is false. The two answer different questions: the
		// outcome reports whether the FAILURE itself had a foreign cause, while
		// this flag reports that the RESERVATION is unresolved — a nonzero exit
		// cannot be distinguished from a CLI-side failure, so the hold may never
		// be silently considered settled. Do not "fix" this to outcome.ExecutionUncertain.
		base["ok"] = false
		base["error"] = "task_failed"
		base["reason_code"] = "task_failed"
		base["execution_uncertain"] = true
		base["note"] = "命令未成功；非零退出与 CLI 侧失败无法区分，预留保持未决等待管理员对账，不会自动重放"
		writeJSON(w, http.StatusBadGateway, base)
	default:
		// timed_out / output_limited / pipe_timeout: we stopped observing.
		base["ok"] = false
		base["error"] = "execution_uncertain"
		base["reason_code"] = "execution_uncertain"
		base["execution_uncertain"] = true
		base["note"] = "本地边界触发，远端可能仍在运行；预留保持未决等待管理员对账，不会自动重放"
		writeJSON(w, http.StatusBadGateway, base)
	}
}

func boolWord(b bool) string {
	if b {
		return "true"
	}
	return "false"
}

type openshellTaskPreviewRequest struct {
	Target string `json:"target"`
}

// Preview is advisory read-only: it never consumes a reservation, never
// executes, and never claims the constraints below are verified.
func (s *Server) openshellTaskPreview(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST required"})
		return
	}
	var body openshellTaskPreviewRequest
	if err := readJSONStrict(r, &body, 4<<10); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	if body.Target == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "target required"})
		return
	}
	if !s.openshellExecL3Gate(w) {
		return
	}
	grantIDs, allow, err := s.targetGrantAllow(body.Target)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "store unreadable"})
		return
	}
	if len(allow) == 0 {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "target_not_authorized", "reason_code": "target_not_authorized"})
		return
	}
	authorized := make([]string, 0, len(allow))
	for ep := range allow {
		authorized = append(authorized, ep)
	}
	sort.Strings(authorized)
	resp := map[string]any{
		"mode": "advisory", "target": body.Target, "grant_ids": grantIDs, "authorized_endpoints": authorized,
		"scope": "task_execution",
		// Contract honesty: this route does not execute, so it can neither
		// demonstrate nor verify any execution constraint.
		"execution_constraints_verified": false, "task_executed": false,
		"note": "预览汇总当前有效授权；实际执行必须绑定单个 Grant 与完整批准参数，且以真实退出状态为准",
	}
	if snap, err := s.d.Openshell.ReadEffective(body.Target); err != nil {
		resp["live_error"] = sanitizeOpenshellErr(err)
	} else {
		resp["live"] = map[string]any{
			"revision": snap.Revision, "policy_digest": snap.PolicyDigest,
			"endpoints": networkEndpoints(snap.Network),
		}
		// This is a current gateway observation for an approver to include in
		// params, not an assertion that execution or policy loading is verified.
		if sandboxID, idErr := s.d.Openshell.CurrentTaskSandboxID(body.Target, snap.Revision); idErr == nil {
			resp["live"].(map[string]any)["sandbox_id"] = sandboxID
		} else {
			resp["live_instance_error"] = sanitizeOpenshellErr(idErr)
		}
	}
	writeJSON(w, http.StatusOK, resp)
}
