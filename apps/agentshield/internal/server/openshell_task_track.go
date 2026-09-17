package server

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/openshell"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/signing"
)

// Durable tracking, stop and reconciliation for real OpenShell task executions.
//
// The projection below is a PURE READ of two durable sources: the signature
// verified receipt chain and the immutable evidence documents written by the
// execute route. It takes nothing from the caller except the identity it uses
// to FIND the reservation, and it writes nothing. In particular it never calls
// ReadHoldExecutionStatus: that engine read requires the full approved params
// (validateExecutionStatusRequest rejects a nil Params), the public status
// request contract deliberately carries no params, and demanding them would
// mean trusting caller-supplied bytes to answer a question about signed state.
//
// What this file deliberately cannot do:
//   - it cannot resume, replay or re-execute anything (no path from here to
//     ExecTask, ReserveHoldExecution or any tool);
//   - it cannot promote an observation into a closed outcome — only an
//     administrator reconciliation closes an unresolved reservation, and that
//     writes a signed receipt through the existing engine call;
//   - it cannot claim the remote task stopped. `remote_stop` is the schema
//     constant "unsupported" and `remote_stop_confirmed` is the constant false,
//     because SIQ currently has no verified per-task remote stop path (design doc §5).

const (
	openshellTaskStatusSchema      = "openshell-task-execution-status/v1"
	openshellTaskStatusReqSchema   = "openshell-task-execution-status-request/v1"
	openshellTaskStopSchema        = "openshell-task-execution-stop/v1"
	openshellTaskReconcileSchema   = "openshell-task-execution-reconcile/v1"
	openshellTaskExecutionKind     = "real_sandbox_command"
	openshellTaskPlanKind          = "openshell_task_execution_plan"
	openshellTaskStartKind         = "openshell_task_execution_start"
	openshellTaskOutcomeKind       = "openshell_task_execution_outcome"
	openshellTaskStopKind          = "openshell_task_execution_stop"
	openshellTaskReservationRecord = "hold_reservation"
	openshellTaskReconcileRecord   = "hold_reconciliation"
	taskEvidenceIntegritySchema    = "siq-task-evidence-ed25519/v1"
	taskEvidenceSignatureDomain    = "siq-task-evidence/v1\x00"
)

// Task evidence is immutable through the Store API, but its JSON files are not
// part of the signed receipt chain. A local writer could otherwise change an
// outcome into "succeeded" and the read-only projection would promote that
// editable flag to a fact. Sign each document under a separate domain before
// writing it and verify it before ANY field is used in a status projection.
func (s *Server) signTaskEvidence(doc map[string]any) error {
	if s.d.Key == nil || doc == nil {
		return errors.New("task evidence signing unavailable")
	}
	delete(doc, "signature")
	doc["integrity_schema"] = taskEvidenceIntegritySchema
	raw, err := json.Marshal(doc)
	if err != nil {
		return err
	}
	doc["signature"] = s.d.Key.SignBytes(append([]byte(taskEvidenceSignatureDomain), raw...))
	return nil
}

func (s *Server) verifyTaskEvidence(doc map[string]any) bool {
	if doc == nil || s.d.Key == nil || taskDocString(doc, "integrity_schema") != taskEvidenceIntegritySchema {
		return false
	}
	sig := taskDocString(doc, "signature")
	unsigned := make(map[string]any, len(doc)-1)
	for key, value := range doc {
		if key != "signature" {
			unsigned[key] = value
		}
	}
	raw, err := json.Marshal(unsigned)
	return err == nil && signing.VerifyBytes(s.d.Key.Public(),
		append([]byte(taskEvidenceSignatureDomain), raw...), sig)
}

// openshellTaskStopEvidenceID names the durable stop record. It is written
// BEFORE the local termination is issued so a crash cannot lose the fact that a
// human asked for a stop; the projection must be able to say "requested" even
// when the process died before it acted.
func openshellTaskStopEvidenceID(reservationReceiptID string) string {
	sum := sha256.Sum256([]byte("ostop|" + reservationReceiptID))
	return "ostop-" + hex.EncodeToString(sum[:8])
}

// ---------------------------------------------------------------- doc reads

func taskDocString(doc map[string]any, key string) string {
	if doc == nil {
		return ""
	}
	s, _ := doc[key].(string)
	return s
}

func taskDocBool(doc map[string]any, key string) bool {
	if doc == nil {
		return false
	}
	b, _ := doc[key].(bool)
	return b
}

func taskDocInt(doc map[string]any, key string) (int, bool) {
	if doc == nil {
		return 0, false
	}
	switch v := doc[key].(type) {
	case float64:
		return int(v), true
	case int:
		return v, true
	case int64:
		return int(v), true
	default:
		return 0, false
	}
}

// taskHex64 mirrors the schema's digest pattern. It is used before emitting any
// document: an unverifiable digest degrades the reported state to uncertain
// rather than producing a schema-invalid answer.
func taskHex64(value string) bool {
	if len(value) != 64 {
		return false
	}
	for _, c := range value {
		if (c < '0' || c > '9') && (c < 'a' || c > 'f') {
			return false
		}
	}
	return true
}

func taskTimestamp(value string) (string, bool) {
	if value == "" {
		return "", false
	}
	t, err := time.Parse(time.RFC3339, value)
	if err != nil {
		return "", false
	}
	return t.UTC().Format(time.RFC3339), true
}

// taskRuntimeTaskID replicates receipt.receiptRuntimeTaskID, which is
// unexported in package receipt: an omitted runtime task id falls back to the
// task id.
func taskRuntimeTaskID(taskID, runtimeTaskID string) string {
	if runtimeTaskID != "" {
		return runtimeTaskID
	}
	return taskID
}

// ------------------------------------------------------------- chain facts

// taskReservationFacts is everything the signed chain alone can prove about one
// reservation. Nothing here comes from the request.
type taskReservationFacts struct {
	Reservation    *receipt.Receipt
	Reconciliation *receipt.Receipt
	Observation    *receipt.Receipt
	TaskID         string
	RuntimeTaskID  string
	Target         string
}

// taskChainFacts verifies the whole chain and then locates the reservation. A
// chain that does not verify proves nothing, so every caller stops there
// instead of reporting a state derived from unverified bytes.
func (s *Server) taskChainFacts(reservationReceiptID string) (*taskReservationFacts, string) {
	receipts, err := s.d.Chain.Read()
	if err != nil || receipt.Verify(receipts, s.d.Key.Public()) != nil {
		return nil, "openshell_chain_unverified"
	}
	facts := &taskReservationFacts{}
	for i := range receipts {
		rec := &receipts[i]
		if rec.ReceiptID == reservationReceiptID && rec.RecordType == openshellTaskReservationRecord {
			facts.Reservation = rec
		}
		// The reconciliation receipt binds to the reservation it closes, not to
		// the original decision, so it is found by DecisionReceiptID.
		if rec.RecordType == openshellTaskReconcileRecord && rec.DecisionReceiptID == reservationReceiptID {
			facts.Reconciliation = rec
		}
		if rec.RecordType == "observation" && rec.DecisionReceiptID == reservationReceiptID &&
			rec.ReceiptID == reservationReceiptID+"-obs" {
			facts.Observation = rec
		}
	}
	if facts.Reservation == nil {
		return nil, "openshell_task_reservation_unknown"
	}
	rec := facts.Reservation
	facts.TaskID = rec.TaskID
	facts.RuntimeTaskID = taskRuntimeTaskID(rec.TaskID, rec.RuntimeTaskID)
	if rec.AgentID != nil {
		facts.Target = *rec.AgentID
	}
	return facts, ""
}

// matchesRequest checks the request against signed receipt fields only, never
// against the request's own claims.
//
// The mandatory identity fields (platform, session, agent, tool, action and
// decision receipt) must agree with the chain exactly. The two task identity
// fields follow the published contracts instead: neither
// openshell-task-execution-status-request.v1 nor
// openshell-task-execution-stop.v1 lists task_id or runtime_task_id as
// required, and the stop contract has no task_id field at all. An omitted field
// therefore takes the chain's value, exactly as the receipt's own fallback
// rule does. Requiring them here would make /status unreadable for every
// execution whose submission carried no task id and /stop unreachable for every
// execution whose submission did.
func (f *taskReservationFacts) matchesRequest(req openshellTaskStatusRequest) bool {
	rec := f.Reservation
	if req.Platform != rec.Platform ||
		req.SessionID != rec.SessionID ||
		req.AgentID != f.Target ||
		req.Tool != rec.Tool ||
		req.ActionID != rec.ActionID ||
		req.DecisionReceiptID != rec.DecisionReceiptID {
		return false
	}
	if req.TaskID != "" && req.TaskID != f.TaskID {
		return false
	}
	// f.RuntimeTaskID already carries the chain's fallback (runtime task id, else
	// task id), so a supplied runtime task id is compared against the value the
	// engine would compare it against.
	return req.RuntimeTaskID == "" || req.RuntimeTaskID == f.RuntimeTaskID
}

// -------------------------------------------------------------- projection

type openshellTaskStatusRequest struct {
	SchemaVersion        string `json:"schema_version"`
	Platform             string `json:"platform"`
	SessionID            string `json:"session_id"`
	AgentID              string `json:"agent_id"`
	TaskID               string `json:"task_id,omitempty"`
	RuntimeTaskID        string `json:"runtime_task_id,omitempty"`
	Tool                 string `json:"tool"`
	ActionID             string `json:"action_id"`
	DecisionReceiptID    string `json:"decision_receipt_id"`
	ReservationReceiptID string `json:"reservation_receipt_id"`
}

func validTaskStatusRequest(req openshellTaskStatusRequest) bool {
	return req.SchemaVersion == openshellTaskStatusReqSchema &&
		validExecutionText(req.Platform, 64) &&
		validExecutionText(req.SessionID, 256) &&
		validExecutionText(req.AgentID, 256) &&
		validExecutionText(req.Tool, 64) && req.Tool == "exec" &&
		validExecutionText(req.ActionID, 256) &&
		validExecutionText(req.DecisionReceiptID, 256) &&
		validExecutionText(req.ReservationReceiptID, 256) &&
		// Optional in openshell-task-execution-status-request.v1, and absent from
		// the stop contract entirely: an omitted task identity means "the one the
		// reservation names", not "invalid".
		validOptionalExecutionText(req.TaskID, 256) &&
		validOptionalExecutionText(req.RuntimeTaskID, 256)
}

func validExecutionText(value string, limit int) bool {
	return value != "" && len(value) <= limit && !strings.ContainsAny(value, "\x00")
}

// validOptionalExecutionText is the optional-field variant of
// validExecutionText: empty is allowed, present values are still bounded and
// NUL-free.
func validOptionalExecutionText(value string, limit int) bool {
	return len(value) <= limit && !strings.ContainsAny(value, "\x00")
}

// taskEvidence bundles the immutable documents the execute route wrote. A
// present-but-unreadable document is never treated as absent.
type taskEvidence struct {
	Plan    map[string]any
	Start   map[string]any
	Outcome map[string]any
	Stop    map[string]any
}

func (s *Server) readTaskEvidence(reservationReceiptID string) (*taskEvidence, string) {
	ev := &taskEvidence{}
	docs := []struct {
		id, kind string
		dest     *map[string]any
	}{
		{openshellTaskPlanEvidenceID(reservationReceiptID), openshellTaskPlanKind, &ev.Plan},
		{openshellTaskStartEvidenceID(reservationReceiptID), openshellTaskStartKind, &ev.Start},
		{openshellTaskEvidenceID(reservationReceiptID), openshellTaskOutcomeKind, &ev.Outcome},
		{openshellTaskStopEvidenceID(reservationReceiptID), openshellTaskStopKind, &ev.Stop},
	}
	for _, d := range docs {
		doc, err := s.d.Store.GetEvidence(d.id)
		if err != nil {
			return nil, "task_evidence_unreadable"
		}
		if doc != nil && (!s.verifyTaskEvidence(doc) ||
			taskDocString(doc, "reservation_receipt_id") != reservationReceiptID ||
			taskDocString(doc, "kind") != d.kind) {
			return nil, "task_evidence_unverified"
		}
		*d.dest = doc
	}
	return ev, ""
}

// A successful outcome has a stronger durable witness: the signed observation
// receipt binds to the exact serialized outcome. A signed local evidence file
// without that chain entry is not a completed, correlated observation.
func (f *taskReservationFacts) matchesObservedOutcome(outcome map[string]any) bool {
	if f == nil || f.Reservation == nil || f.Observation == nil {
		return false
	}
	obs, rec := f.Observation, f.Reservation
	if obs.DecisionReceiptID != rec.ReceiptID || obs.ActionID != rec.ActionID ||
		obs.Platform != rec.Platform || obs.SessionID != rec.SessionID ||
		obs.Tool != rec.Tool || obs.Action != receipt.ActionAllow ||
		obs.AgentID == nil || rec.AgentID == nil || *obs.AgentID != *rec.AgentID {
		return false
	}
	raw, err := json.Marshal(outcome)
	if err != nil {
		return false
	}
	sum := sha256.Sum256(raw)
	return obs.ParamsDigest == hex.EncodeToString(sum[:])
}

// taskStatusProjection answers "what can be proven about this reservation right
// now" from verified chain state plus immutable documents. It is the single
// source for both the status and the stop routes.
//
// Precedence, most specific provable fact first:
//  1. a refusal that is provably a POLICY-side fact — it must not be erased by
//     the automatic not_occurred reconciliation that follows it (design doc I6);
//  2. an administrator reconciliation — it is the deliberate closure of an
//     unresolved reservation and postdates everything else;
//  3. the recorded outcome of the run;
//  4. a recorded stop request;
//  5. a recorded launch with no outcome (running here, else uncertain);
//  6. the reservation alone (reserved, or expired).
func (s *Server) taskStatusProjection(facts *taskReservationFacts, req openshellTaskStatusRequest, ev *taskEvidence) (map[string]any, int, string) {
	rec := facts.Reservation
	plan := ev.Plan
	if plan == nil || taskDocString(plan, "kind") != openshellTaskPlanKind {
		// Without the plan record a restart cannot say which command the
		// reservation referred to, so no schema-valid status can be built.
		return nil, http.StatusServiceUnavailable, "task_plan_missing"
	}
	policyRevision := taskDocString(plan, "policy_revision")
	policyDigest := taskDocString(plan, "policy_digest")
	argvDigest := taskDocString(plan, "argv_digest")
	if !canonicalRevision(policyRevision) || !taskHex64(policyDigest) || !taskHex64(argvDigest) {
		return nil, http.StatusServiceUnavailable, "task_plan_missing"
	}

	doc := map[string]any{
		"schema_version":         openshellTaskStatusSchema,
		"task_execution_kind":    openshellTaskExecutionKind,
		"execution_id":           rec.ReceiptID,
		"action_id":              rec.ActionID,
		"decision_receipt_id":    rec.DecisionReceiptID,
		"reservation_receipt_id": rec.ReceiptID,
		"platform":               rec.Platform,
		"session_id":             rec.SessionID,
		"agent_id":               facts.Target,
		"tool":                   rec.Tool,
		"target":                 facts.Target,
		// The chain stores the task identity it was reserved under; the request
		// only ever had to name a subset.
		"policy_revision": policyRevision,
		"policy_digest":   policyDigest,
		"argv_digest":     argvDigest,
	}
	if facts.TaskID != "" {
		doc["task_id"] = facts.TaskID
		doc["runtime_task_id"] = facts.RuntimeTaskID
	}
	if timeout, ok := taskDocInt(plan, "timeout_seconds"); ok && timeout >= 1 && timeout <= 900 {
		doc["timeout_seconds"] = timeout
	}

	outcome := ev.Outcome
	if outcome != nil && taskDocString(outcome, "kind") != openshellTaskOutcomeKind {
		outcome = nil
	}
	refusal := taskDocString(outcome, "refusal")
	stopBeforeSpawn := refusal == openshell.TaskRefusalStopBeforeSpawn
	// A stop that arrived before the child existed is a refusal record, but it
	// is not a denial: the human asked for the stop and nothing ran. It is
	// routed past (1) so the reconciliation the execute route wrote closes it
	// as not_occurred, which is what actually happened.
	refused := outcome != nil && taskDocBool(outcome, "preflight_refused") && !stopBeforeSpawn

	// (1) Policy-side refusal. The automatic reconciliation that follows a
	// refusal proves the task did not run; it does not prove the policy was
	// loaded, and the two facts are kept in separate books.
	if refused && refusal == "openshell_task_policy_not_loaded" {
		return taskDeniedStatus(doc, "policy_unverified", "openshell_task_policy_not_loaded",
			"策略读回与批准值不符或读不到；任务侧未发起，策略侧事实单独留账"), http.StatusOK, ""
	}
	if refused && refusal == "openshell_task_backend_unbound" {
		return taskDeniedStatus(doc, "denied", "openshell_task_backend_unbound",
			"后端指纹为空；拒绝执行且不回落本地 native"), http.StatusOK, ""
	}
	if refused {
		code := "openshell_task_denied_binding"
		if refusal == "openshell_task_not_authorized" {
			code = "openshell_task_denied_grant"
		}
		return taskDeniedStatus(doc, "denied", code, "执行前校验未通过，未产生任务副作用"), http.StatusOK, ""
	}

	// (2) Administrator reconciliation: the only way an unresolved reservation
	// is ever closed, and it is read-only with respect to the task.
	if facts.Reconciliation != nil {
		state, reason := "reconciled_not_occurred", "openshell_task_confirmed_not_occurred"
		if facts.Reconciliation.Action == receipt.ActionAllow {
			state, reason = "reconciled_occurred", "openshell_task_confirmed_occurred"
		}
		doc["state"] = state
		doc["reason_code"] = reason
		doc["reconciliation_receipt_id"] = facts.Reconciliation.ReceiptID
		doc["note"] = "管理员凭外部证据结案；不重放、不改写既有观测"
		return doc, http.StatusOK, ""
	}

	// (3) The recorded outcome.
	if outcome != nil {
		if taskDocString(outcome, "state") == openshell.TaskStateSucceeded && !facts.matchesObservedOutcome(outcome) {
			doc["state"] = "uncertain"
			doc["reason_code"] = "openshell_task_result_uncertain"
			doc["note"] = "本地成功记录缺少匹配的签名观察回执；预留保持未决，不重放任务"
			return doc, http.StatusOK, ""
		}
		if stateDoc, ok := taskOutcomeStatus(doc, outcome, ev.Stop); ok {
			return stateDoc, http.StatusOK, ""
		}
		doc["state"] = "uncertain"
		doc["reason_code"] = "openshell_task_result_uncertain"
		doc["note"] = "已记录的执行结果不足以支撑终态；预留保持未决等待管理员对账"
		return doc, http.StatusOK, ""
	}

	// (4) A recorded stop request. The state name says what was requested, not
	// what happened remotely.
	if ev.Stop != nil && taskDocString(ev.Stop, "kind") == openshellTaskStopKind {
		requestedAt, ok := taskTimestamp(firstNonEmpty(taskDocString(ev.Stop, "requested_at"), taskDocString(ev.Stop, "recorded_at")))
		if !ok {
			doc["state"] = "uncertain"
			doc["reason_code"] = "openshell_task_result_uncertain"
			doc["note"] = "停止记录时间戳不可读；无法给出可证的停止状态"
			return doc, http.StatusOK, ""
		}
		doc["state"] = "stop_requested"
		doc["reason_code"] = "openshell_task_stop_requested_local_only"
		stop := map[string]any{
			"requested_at":          requestedAt,
			"local_cli_termination": taskStopTermination(ev.Stop),
			"remote_stop":           "unsupported",
			"remote_stop_confirmed": false,
			"note":                  "本地 CLI 终止不等于远端任务已停止；SIQ 当前未接入远端停止确认",
		}
		if actor := taskDocString(ev.Stop, "actor_id"); actor != "" && len(actor) <= 128 {
			stop["actor_id"] = actor
		}
		doc["stop"] = stop
		return doc, http.StatusOK, ""
	}

	// (5) A recorded launch with no outcome.
	if ev.Start != nil && taskDocString(ev.Start, "kind") == openshellTaskStartKind {
		startedAt, ok := taskTimestamp(taskDocString(ev.Start, "recorded_at"))
		if ok && s.d.Openshell != nil && s.d.Openshell.IsObservingLocalTask(rec.ReceiptID) {
			doc["state"] = "running"
			doc["reason_code"] = "openshell_task_running"
			doc["started_at"] = startedAt
			doc["note"] = "本进程正在观测该子进程"
			return doc, http.StatusOK, ""
		}
		doc["state"] = "uncertain"
		doc["reason_code"] = "openshell_task_result_uncertain"
		doc["note"] = "发起标记存在但结果未知（进程重启或本进程不再观测）；只做对账，不自动重放"
		if ok {
			doc["started_at"] = startedAt
		}
		return doc, http.StatusOK, ""
	}

	// (6) The reservation alone: nothing was ever launched.
	if expiresAt, ok := taskTimestamp(taskDocString(plan, "reservation_expires_at")); ok {
		if deadline, err := time.Parse(time.RFC3339, expiresAt); err == nil && !time.Now().UTC().Before(deadline) {
			doc["state"] = "denied"
			doc["reason_code"] = "openshell_task_reservation_expired"
			doc["note"] = "预留已过期，未发起任何执行"
			return doc, http.StatusOK, ""
		}
	}
	doc["state"] = "reserved"
	doc["reason_code"] = "openshell_task_reserved"
	doc["note"] = "已写入持久预留，尚无任何发起记录"
	return doc, http.StatusOK, ""
}

func taskDeniedStatus(doc map[string]any, state, reason, note string) map[string]any {
	doc["state"] = state
	doc["reason_code"] = reason
	doc["note"] = note
	return doc
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}

// taskStopTermination reports the honest local fact. "terminated" and "refused"
// are left unused in v1: we issue the cancellation to a live handle and do not
// synchronously observe the child's exit, so claiming "terminated" would
// overstate what we know.
func taskStopTermination(stopDoc map[string]any) string {
	if taskDocString(stopDoc, "local_cli_termination") == "requested" {
		return "requested"
	}
	return "not_running"
}

// taskOutcomeStatus maps a durable outcome document onto the state machine.
// Returns false when the document cannot support a terminal answer, in which
// case the caller degrades to uncertain rather than inventing a result.
func taskOutcomeStatus(doc map[string]any, outcome map[string]any, stopDoc map[string]any) (map[string]any, bool) {
	stdout := taskDocString(outcome, "stdout_digest")
	stderr := taskDocString(outcome, "stderr_digest")
	bytes, _ := taskDocInt(outcome, "stdout_bytes")
	if bytes < 0 {
		bytes = 0
	}
	truncated := taskDocString(outcome, "bound_fired") == "output_limit"
	exitCode, hasExit := taskDocInt(outcome, "exit_code")
	if hasExit {
		if exitCode < -1 {
			exitCode = -1
		}
		if exitCode > 255 {
			exitCode = 255
		}
	}
	if startedAt, ok := taskTimestamp(taskDocString(outcome, "started_at")); ok {
		doc["started_at"] = startedAt
	}
	if finishedAt, ok := taskTimestamp(taskDocString(outcome, "finished_at")); ok {
		doc["finished_at"] = finishedAt
	}
	output := func() map[string]any {
		out := map[string]any{
			"digest": stdout, "bytes": bytes, "truncated": truncated,
			"raw_stored": false, "raw_opt_in": false,
		}
		if taskHex64(stderr) {
			out["stderr_digest"] = stderr
		}
		return out
	}

	switch taskDocString(outcome, "state") {
	case "succeeded":
		// rc == 0 is the only documented remote success. Anything else here
		// means the record and the mapping disagree: refuse to call it success.
		if !hasExit || exitCode != 0 || !taskHex64(stdout) {
			return nil, false
		}
		doc["state"] = "succeeded"
		doc["reason_code"] = "openshell_task_succeeded"
		doc["remote_exit_code"] = 0
		doc["output"] = output()
		return doc, true
	case "failed":
		if !hasExit || !taskHex64(stdout) {
			return nil, false
		}
		doc["state"] = "failed"
		doc["reason_code"] = "openshell_task_failed"
		doc["remote_exit_code"] = exitCode
		doc["output"] = output()
		doc["note"] = "非零退出与 CLI 侧失败无法区分；预留保持未决等待管理员对账"
		return doc, true
	case "output_limited":
		if !taskHex64(stdout) {
			return nil, false
		}
		doc["state"] = "output_limited"
		doc["reason_code"] = "openshell_task_output_limited"
		doc["output"] = output()
		doc["note"] = "输出超过批准上限被截断；远端任务可能仍在运行"
		return doc, true
	case "timed_out":
		// The bound that fires locally is our own observation window. The
		// backend --timeout is never asserted as the cause, because a remote
		// timeout is indistinguishable from an ordinary nonzero exit here.
		doc["state"] = "timed_out"
		doc["reason_code"] = "openshell_task_timeout_local"
		doc["timeout_bound_that_fired"] = "local"
		doc["note"] = "本地有界观测触发；远端可能仍在运行"
		return doc, true
	case "stop_requested":
		// A local cancellation is recorded here. It names what was requested,
		// never what happened remotely, so the stop block reports the schema's
		// constants rather than a claim.
		requestedAt, ok := taskTimestamp(firstNonEmpty(
			taskDocString(stopDoc, "requested_at"),
			taskDocString(outcome, "finished_at"),
			taskDocString(outcome, "started_at")))
		if !ok {
			return nil, false
		}
		doc["state"] = "stop_requested"
		doc["reason_code"] = "openshell_task_stop_requested_local_only"
		stop := map[string]any{
			"requested_at":          requestedAt,
			"local_cli_termination": "requested",
			"remote_stop":           "unsupported",
			"remote_stop_confirmed": false,
			"note":                  "本地 CLI 终止不等于远端任务已停止；SIQ 当前未接入远端停止确认",
		}
		if stopDoc != nil {
			stop["local_cli_termination"] = taskStopTermination(stopDoc)
			if actor := taskDocString(stopDoc, "actor_id"); actor != "" && len(actor) <= 128 {
				stop["actor_id"] = actor
			}
		}
		doc["stop"] = stop
		return doc, true
	}
	return nil, false
}

// ---------------------------------------------------------------- handlers

// openshellTaskStatus is a read-only projection. It deliberately does NOT go
// through the L3 backend gate: durable state must stay readable exactly when
// the backend is unreachable, which is when an operator needs it most.
//
// It is registered twice in the mux — on /status with a decision credential and
// on /read with an administrator session — because the management console has
// no decision credential and must still be able to see the state of a task it
// approved. Both registrations call this one function, so the two routes cannot
// drift into disagreeing about what happened; the capability gate, not the
// handler, is what differs.
func (s *Server) openshellTaskStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST required"})
		return
	}
	var body openshellTaskStatusRequest
	if err := readJSONStrict(r, &body, 8<<10); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	if !validTaskStatusRequest(body) {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"error": "invalid_openshell_task_status_shape", "reason_code": "invalid_openshell_task_status_shape"})
		return
	}
	doc, code, errCode := s.taskStatusFor(body)
	if errCode != "" {
		writeJSON(w, code, map[string]string{"error": errCode, "reason_code": errCode})
		return
	}
	writeJSON(w, http.StatusOK, doc)
}

// taskStatusFor is the shared read path used by all three routes.
func (s *Server) taskStatusFor(body openshellTaskStatusRequest) (map[string]any, int, string) {
	facts, errCode := s.taskChainFacts(body.ReservationReceiptID)
	if errCode != "" {
		code := http.StatusServiceUnavailable
		if errCode == "openshell_task_reservation_unknown" {
			code = http.StatusNotFound
		}
		return nil, code, errCode
	}
	if !facts.matchesRequest(body) {
		return nil, http.StatusNotFound, "openshell_task_reservation_mismatch"
	}
	ev, errCode := s.readTaskEvidence(body.ReservationReceiptID)
	if errCode != "" {
		return nil, http.StatusServiceUnavailable, errCode
	}
	return s.taskStatusProjection(facts, body, ev)
}

// openshellTaskStop records a stop request and then terminates LOCAL
// observation. It is not a sandbox stop: SIQ has no verified per-task remote
// stop path, and deleting the sandbox is never a substitute.
func (s *Server) openshellTaskStop(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST required"})
		return
	}
	var body openshellTaskStopRequest
	if err := readJSONStrict(r, &body, 16<<10); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	if !validTaskStopRequest(body) {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"error": "invalid_openshell_task_stop_shape", "reason_code": "invalid_openshell_task_stop_shape"})
		return
	}
	statusReq := body.statusRequest()
	facts, errCode := s.taskChainFacts(body.ReservationReceiptID)
	if errCode != "" {
		code := http.StatusServiceUnavailable
		if errCode == "openshell_task_reservation_unknown" {
			code = http.StatusNotFound
		}
		writeJSON(w, code, map[string]string{"error": errCode, "reason_code": errCode})
		return
	}
	// Ownership is checked against signed state, never against the request's own
	// claims: a caller who names a foreign task must not be able to reach its
	// local handle.
	if !facts.matchesRequest(statusReq) {
		writeJSON(w, http.StatusForbidden, map[string]string{
			"error": "openshell_task_stop_identity_mismatch", "reason_code": "openshell_task_stop_identity_mismatch"})
		return
	}
	ev, errCode := s.readTaskEvidence(body.ReservationReceiptID)
	if errCode != "" {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": errCode, "reason_code": errCode})
		return
	}
	if ev.Plan == nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{
			"error": "task_plan_missing", "reason_code": "task_plan_missing"})
		return
	}
	if s.d.Openshell == nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "OpenShell CLI 未配置"})
		return
	}
	// Hold the process-local handle stable across audit, immutable evidence,
	// and cancellation. Without this, the run can release its handle between
	// IsObservingLocalTask and StopLocalTask, yielding a false 200 response.
	// The stop record is durable BEFORE cancellation; a failed write does not
	// cancel, and a crash after the write still leaves the request visible.
	var stopDoc map[string]any
	recordCode := ""
	observing, recordErr := s.d.Openshell.StopLocalTaskRecorded(body.ReservationReceiptID, func(active bool) error {
		if err := s.appendTaskAudit("openshell_task_stop_requested", facts.Target,
			"reservation="+body.ReservationReceiptID); err != nil {
			recordCode = "stop_audit_not_persisted"
			return err
		}
		termination := "not_running"
		if active {
			termination = "requested"
		}
		stopDoc = s.persistTaskStop(facts, body, termination)
		if stopDoc == nil {
			recordCode = "stop_not_recorded"
			return errors.New(recordCode)
		}
		return nil
	})
	if recordErr != nil {
		note := "停止请求未能落盘，因此未发出任何终止动作"
		if recordCode == "stop_audit_not_persisted" {
			note = "停止请求审计失败，未发出任何停止动作"
		}
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"ok": false, "error": recordCode, "reason_code": recordCode,
			"scope": "task_execution", "note": note,
		})
		return
	}

	ev.Stop = stopDoc
	doc, _, errCode := s.taskStatusProjection(facts, statusReq, ev)
	if errCode != "" {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": errCode, "reason_code": errCode})
		return
	}
	if !observing {
		// Nothing was running in this process. That is NOT evidence the remote
		// task stopped, so the request is recorded but the response is an error.
		writeJSON(w, http.StatusConflict, map[string]any{
			"ok": false, "error": "stop_not_observable", "reason_code": "stop_not_observable",
			"scope": "task_execution",
			// Literal so the containment below cannot be relaxed by accident.
			"remote_stopped": false,
			"status":         doc,
			"note":           "本进程未观测到该任务，未发出任何终止动作；本地未运行不等于远端任务已停止",
		})
		return
	}
	writeJSON(w, http.StatusOK, doc)
}

// persistTaskStop writes the immutable stop record. The doc intentionally has
// no field that could be read as remote confirmation.
func (s *Server) persistTaskStop(facts *taskReservationFacts, body openshellTaskStopRequest, termination string) map[string]any {
	now := time.Now().UTC().Format(time.RFC3339)
	doc := map[string]any{
		"kind":                   openshellTaskStopKind,
		"reservation_receipt_id": facts.Reservation.ReceiptID,
		"action_id":              facts.Reservation.ActionID,
		"decision_receipt_id":    facts.Reservation.DecisionReceiptID,
		"target":                 facts.Target,
		"platform":               facts.Reservation.Platform,
		"session_id":             facts.Reservation.SessionID,
		"agent_id":               facts.Target,
		"tool":                   facts.Reservation.Tool,
		"actor_id":               strings.TrimSpace(body.ActorID),
		"local_cli_termination":  termination,
		"remote_stop":            "unsupported",
		"remote_stop_confirmed":  false,
		"delete_sandbox":         false,
		"requested_at":           now,
		"recorded_at":            now,
	}
	if body.Reason != "" {
		doc["reason"] = body.Reason
	}
	if s.signTaskEvidence(doc) != nil {
		return nil
	}
	if s.d.Store.PutEvidence(openshellTaskStopEvidenceID(facts.Reservation.ReceiptID), doc) != nil {
		return nil
	}
	return doc
}

type openshellTaskStopRequest struct {
	SchemaVersion        string `json:"schema_version"`
	ReservationReceiptID string `json:"reservation_receipt_id"`
	ActionID             string `json:"action_id"`
	DecisionReceiptID    string `json:"decision_receipt_id"`
	Target               string `json:"target"`
	Platform             string `json:"platform"`
	SessionID            string `json:"session_id"`
	AgentID              string `json:"agent_id"`
	Tool                 string `json:"tool"`
	ActorID              string `json:"actor_id"`
	// Constant false in the contract. A pointer so an explicit true is
	// distinguishable from an omitted field, and deleting the sandbox as a
	// substitute for stopping is refused rather than ignored.
	DeleteSandbox *bool  `json:"delete_sandbox,omitempty"`
	Reason        string `json:"reason,omitempty"`
}

func (b openshellTaskStopRequest) statusRequest() openshellTaskStatusRequest {
	return openshellTaskStatusRequest{
		SchemaVersion: openshellTaskStatusReqSchema,
		Platform:      b.Platform, SessionID: b.SessionID, AgentID: b.AgentID,
		Tool: b.Tool, ActionID: b.ActionID, DecisionReceiptID: b.DecisionReceiptID,
		ReservationReceiptID: b.ReservationReceiptID,
	}
}

func validTaskStopRequest(b openshellTaskStopRequest) bool {
	return b.SchemaVersion == openshellTaskStopSchema &&
		validExecutionText(b.ReservationReceiptID, 256) &&
		validExecutionText(b.ActionID, 256) &&
		validExecutionText(b.DecisionReceiptID, 256) &&
		validTaskTargetShape(b.Target) &&
		validExecutionText(b.Platform, 64) &&
		validExecutionText(b.SessionID, 256) &&
		validExecutionText(b.AgentID, 256) &&
		b.Tool == "exec" &&
		validStopActor(b.ActorID) &&
		(b.DeleteSandbox == nil || !*b.DeleteSandbox) &&
		len(b.Reason) <= 512
}

// validTaskTargetShape mirrors the contract's target pattern.
func validTaskTargetShape(target string) bool {
	if len(target) == 0 || len(target) > 63 {
		return false
	}
	for i, c := range target {
		switch {
		case c >= 'a' && c <= 'z', c >= 'A' && c <= 'Z', c >= '0' && c <= '9':
		case (c == '.' || c == '_' || c == '-') && i > 0:
		default:
			return false
		}
	}
	return true
}

func validStopActor(actor string) bool {
	actor = strings.TrimSpace(actor)
	if actor == "" || len(actor) > 128 {
		return false
	}
	for _, c := range actor {
		if c < 0x20 || c == 0x7f {
			return false
		}
	}
	return true
}

// openshellTaskReconcile closes one unresolved reservation with an
// administrator's externally verified finding. It re-runs nothing, rewrites no
// observation, and cannot rebuild a missing identity: the signed reservation
// hash must match, and the engine refuses a reservation that already has an
// observation.
func (s *Server) openshellTaskReconcile(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST required"})
		return
	}
	var body openshellTaskReconcileRequest
	if err := readJSONStrict(r, &body, 16<<10); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	if !validTaskReconcileRequest(body) {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"error": "invalid_openshell_task_reconcile_shape", "reason_code": "invalid_openshell_task_reconcile_shape"})
		return
	}
	facts, errCode := s.taskChainFacts(body.ReservationReceiptID)
	if errCode != "" {
		code := http.StatusServiceUnavailable
		if errCode == "openshell_task_reservation_unknown" {
			code = http.StatusNotFound
		}
		writeJSON(w, code, map[string]string{"error": errCode, "reason_code": errCode})
		return
	}
	if facts.Reservation.ActionID != body.ActionID || facts.Reservation.DecisionReceiptID != body.DecisionReceiptID {
		writeJSON(w, http.StatusForbidden, map[string]string{
			"error": "openshell_task_reconcile_identity_mismatch", "reason_code": "openshell_task_reconcile_identity_mismatch"})
		return
	}
	if facts.Reservation.Hash != body.ReservationHash {
		writeJSON(w, http.StatusConflict, map[string]string{
			"error": "openshell_task_reconcile_hash_mismatch", "reason_code": "openshell_task_reconcile_hash_mismatch"})
		return
	}
	// The policy-apply route shares this chain and writes hold_reservation
	// receipts too. Only a reservation this route planned may be reconciled
	// here, or an administrator could close a policy_apply reservation through
	// the task-execution contract.
	plan, err := s.d.Store.GetEvidence(openshellTaskPlanEvidenceID(body.ReservationReceiptID))
	if err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{
			"error": "task_evidence_unreadable", "reason_code": "task_evidence_unreadable"})
		return
	}
	if plan == nil || taskDocString(plan, "kind") != openshellTaskPlanKind {
		writeJSON(w, http.StatusNotFound, map[string]string{
			"error": "openshell_task_reservation_unknown", "reason_code": "openshell_task_reservation_unknown"})
		return
	}
	if err := s.appendTaskAudit("openshell_task_reconcile_requested", facts.Target,
		"reservation="+body.ReservationReceiptID+" outcome="+body.Outcome); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"ok": false, "error": "reconcile_audit_not_persisted", "reason_code": "reconcile_audit_not_persisted",
			"reconciled": false,
		})
		return
	}
	status, err := s.d.Engine.ReconcileHoldExecution(receipt.HoldExecutionReconcile{
		SchemaVersion:        openshellExecSchemaReconcile,
		ActionID:             body.ActionID,
		DecisionReceiptID:    body.DecisionReceiptID,
		ReservationReceiptID: body.ReservationReceiptID,
		ReservationHash:      body.ReservationHash,
		Outcome:              body.Outcome,
		ActorID:              body.ActorID,
	})
	if err != nil {
		code := http.StatusConflict
		reason := "openshell_task_reconcile_conflict"
		if err == receipt.ErrHoldReconciliationInvalid {
			code = http.StatusBadRequest
			reason = "openshell_task_reconcile_invalid"
		}
		writeJSON(w, code, map[string]string{"error": reason, "reason_code": reason,
			"note": sanitizeOpenshellErr(err)})
		return
	}
	s.invalidateProjection("hold_execution_reconciled")
	if err := s.appendTaskAudit("openshell_task_reconcile", facts.Target,
		"reservation="+body.ReservationReceiptID+" outcome="+body.Outcome); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"ok": false, "error": "reconcile_audit_incomplete", "reconciled": true,
			"reconciliation": status, "note": "对账已签名落链，但完成审计失败；不要重放任务",
		})
		return
	}

	// Re-read the projection: the signed chain now carries the closing receipt.
	statusReq := openshellTaskStatusRequest{
		SchemaVersion: openshellTaskStatusReqSchema,
		Platform:      facts.Reservation.Platform, SessionID: facts.Reservation.SessionID,
		AgentID: facts.Target, TaskID: facts.TaskID, RuntimeTaskID: facts.Reservation.RuntimeTaskID,
		Tool: facts.Reservation.Tool, ActionID: facts.Reservation.ActionID,
		DecisionReceiptID:    facts.Reservation.DecisionReceiptID,
		ReservationReceiptID: facts.Reservation.ReceiptID,
	}
	doc, code, errCode := s.taskStatusFor(statusReq)
	if errCode != "" {
		// The signed closure succeeded; report that honestly instead of
		// pretending the whole operation failed.
		writeJSON(w, code, map[string]any{
			"ok": true, "reconciled": true, "reconciliation": status,
			"projection_error": errCode,
			"note":             "对账已签名落链，但状态投影暂不可读",
		})
		return
	}
	writeJSON(w, http.StatusOK, doc)
}

type openshellTaskReconcileRequest struct {
	SchemaVersion        string `json:"schema_version"`
	ReservationReceiptID string `json:"reservation_receipt_id"`
	ReservationHash      string `json:"reservation_hash"`
	ActionID             string `json:"action_id"`
	DecisionReceiptID    string `json:"decision_receipt_id"`
	Outcome              string `json:"outcome"`
	ActorID              string `json:"actor_id"`
	EvidenceNote         string `json:"evidence_note,omitempty"`
}

func validTaskReconcileRequest(b openshellTaskReconcileRequest) bool {
	return b.SchemaVersion == openshellTaskReconcileSchema &&
		validExecutionText(b.ReservationReceiptID, 256) &&
		taskHex64(b.ReservationHash) &&
		validExecutionText(b.ActionID, 256) &&
		validExecutionText(b.DecisionReceiptID, 256) &&
		(b.Outcome == receipt.HoldExecutionOccurred || b.Outcome == receipt.HoldExecutionNotOccurred) &&
		validStopActor(b.ActorID) &&
		len(b.EvidenceNote) <= 512
}
