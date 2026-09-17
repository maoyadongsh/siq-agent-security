package server

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/openshell"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/state"
)

// Experimental policy-apply control-plane integration; not task execution or O05 acceptance.
//
// This file wires the EXISTING authorization planes together; it creates no
// parallel authority:
//   - the hold decision plane (hold approval -> ReserveHoldExecution ->
//     holdAuthorityCurrent) stays the only source of execution permission;
//   - the OpenShell deployment plane (ApplyAndVerify / RollbackAuthorized)
//     stays the only writer to gateway policy;
//   - grant facts stay the only source of authorized network endpoints.
//
// Step ① preview  (openshellSessionPreview)   — read-only, no execution, no
//   permission expansion.
// Step ② execute (openshellSessionExecute)   — consume one reservation, then apply policy (not an atomic backend transaction).
//   Every authorization pre-check runs BEFORE ReserveHoldExecution so a
//   rejection never consumes the human approval; the submitted fields are
//   requests only and are re-checked against signed state server-side.
// Step ③ rollback (openshellSessionRollback) — admin restore of an owned
//   operation, with the outcome recorded via ReconcileHoldExecution.
//
// Outcome honesty (prompt step ⑤): a CAS revision conflict is provable
// no-write and auto-reconciles not_occurred; a write that reached the gateway
// but failed verification is reported execution_uncertain and the reservation
// stays unresolved for admin reconciliation — it is never rewritten as
// "not executed" and never auto-replayed.

const openshellExecSchemaReserve = "hold-execution-reserve/v1"
const openshellExecSchemaReconcile = "hold-execution-reconcile/v1"

type openshellExecBinding struct {
	ActionID          string                         `json:"action_id"`
	DecisionReceiptID string                         `json:"decision_receipt_id"`
	ReservationHash   string                         `json:"reservation_hash"`
	Target            string                         `json:"target"`
	Receipt           openshell.DeploymentReceipt    `json:"receipt"`
	ActorID           string                         `json:"actor_id"`
	Plan              openshellSessionExecuteRequest `json:"-"`
}

// osExecBindings is process-local, exactly like the openshell client's own
// operation registry: rollback binds to an operation this process created.
// The signed chain (reservation + observation + reconciliation receipts)
// remains the durable authority across restarts.
func (s *Server) osExecBindingFor(reservationReceiptID string) (openshellExecBinding, bool) {
	s.osExecMu.Lock()
	defer s.osExecMu.Unlock()
	b, ok := s.osExecBindings[reservationReceiptID]
	return b, ok
}

func (s *Server) osExecPutBinding(reservationReceiptID string, b openshellExecBinding) {
	s.osExecMu.Lock()
	defer s.osExecMu.Unlock()
	if s.osExecBindings == nil {
		s.osExecBindings = map[string]openshellExecBinding{}
	}
	s.osExecBindings[reservationReceiptID] = b
}

func (s *Server) openshellExecL3Gate(w http.ResponseWriter) bool {
	if s.d.Openshell == nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{"error": "OpenShell CLI 未配置"})
		return false
	}
	row := s.openshellPlatform(true)
	if row.Tier != "L3" {
		// Required backend unavailable: refuse, never fall back to native.
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"error": "OpenShell L3 不可用: " + row.Note,
			"note":  "required 后端不可用时不回落 native 执行",
		})
		return false
	}
	return true
}

// targetGrantAllow is an advisory preview of verified, current grants. Its
// union is never used to authorize a write: execute binds to one signed grant.
func (s *Server) targetGrantAllow(target string) (grantIDs []string, allow map[string]bool, err error) {
	grants, err := s.d.Store.ListGrants()
	if err != nil {
		return nil, nil, err
	}
	allow = map[string]bool{}
	for _, g := range grants {
		if g.Subject.ID != target {
			continue
		}
		if g.Status != "deployed" && g.Status != "effective" {
			continue
		}
		if !grant.Verify(s.d.Key.Public(), g) || grant.ValidateLifetime(g, time.Now()) != nil {
			continue
		}
		grantIDs = append(grantIDs, g.GrantID)
		for ep := range grantNetwork(g) {
			allow[ep] = true
		}
	}
	return grantIDs, allow, nil
}

func openshellExecEvidenceID(reservationReceiptID string) string {
	sum := sha256.Sum256([]byte("osx|" + reservationReceiptID))
	return "osx-" + hex.EncodeToString(sum[:8])
}

// chainReceiptHash returns the signed hash of one receipt in the chain, so
// reconciliation can bind the reservation hash from signed state instead of
// trusting the request.
func (s *Server) chainReceiptHash(receiptID string) string {
	receipts, err := s.d.Chain.Read()
	if err != nil || receipt.Verify(receipts, s.d.Key.Public()) != nil {
		return ""
	}
	for _, rec := range receipts {
		if rec.ReceiptID == receiptID && len(rec.Hash) == 64 {
			return rec.Hash
		}
	}
	return ""
}

func (s *Server) reconcileUncertainExecution(reserveStatus *receipt.HoldExecutionStatus, actor, outcome string) (*receipt.HoldExecutionStatus, string) {
	if reserveStatus == nil {
		return nil, "missing reservation status"
	}
	req := receipt.HoldExecutionReconcile{
		SchemaVersion:        openshellExecSchemaReconcile,
		ActionID:             reserveStatus.ActionID,
		DecisionReceiptID:    reserveStatus.DecisionReceiptID,
		ReservationReceiptID: reserveStatus.ReservationReceiptID,
		ReservationHash:      s.chainReceiptHash(reserveStatus.ReservationReceiptID),
		Outcome:              outcome,
		ActorID:              actor,
	}
	status, err := s.d.Engine.ReconcileHoldExecution(req)
	if err != nil {
		return nil, sanitizeOpenshellErr(err)
	}
	s.invalidateProjection("hold_execution_reconciled")
	return status, ""
}

type openshellSessionExecuteRequest struct {
	receipt.HoldExecutionReserve
	Target           string   `json:"target"`
	Endpoints        []string `json:"endpoints"`
	BinaryPaths      []string `json:"binary_paths"`
	ExpectedRevision string   `json:"expected_revision"`
}

func (s *Server) openshellSessionExecute(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST required"})
		return
	}
	var body openshellSessionExecuteRequest
	if err := readJSONStrict(r, &body, 64<<10); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	if !validOpenShellExecutionShape(body) {
		writeJSON(w, 400, map[string]string{"error": "invalid_openshell_operation_shape"})
		return
	}
	endpoints := body.Endpoints
	if !s.openshellExecL3Gate(w) {
		return
	}
	if _, err := s.validateOpenShellExecutionBinding(body); err != nil {
		writeJSON(w, 403, map[string]string{"error": err.Error(), "reason_code": err.Error()})
		return
	}
	// Reserve: consumes the approved hold exactly once, via the existing
	// engine contract. Failures here leave the approval intact.
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
	rules := make([]openshell.NetworkRule, 0, len(endpoints))
	for _, ep := range endpoints {
		rules = append(rules, openshell.NetworkRule{Endpoint: ep, Effect: "allow", BinaryPaths: body.BinaryPaths})
	}
	rec, err := s.d.Openshell.ApplyNetworkAuthorized(body.Target, rules, body.ExpectedRevision, func() error {
		if _, err := s.validateOpenShellExecutionBinding(body); err != nil {
			return err
		}
		return s.d.Engine.RecheckReservedExecution(receipt.HoldExecutionStatusRequest{
			SchemaVersion: "hold-execution-status-request/v1", Platform: body.Platform, SessionID: body.SessionID, AgentID: body.AgentID,
			TaskID: body.TaskID, RuntimeTaskID: body.RuntimeTaskID, Tool: body.Tool, RetryToolCallID: body.RetryToolCallID,
			ActionID: body.ActionID, DecisionReceiptID: body.DecisionReceiptID, ReservationReceiptID: reserveStatus.ReservationReceiptID, Params: body.Params,
		})
	})
	result := openshell.ApplyResult{Receipt: rec}
	if err == nil {
		result.Report = s.d.Openshell.Verify(body.Target, rec, endpoints, nil)
		result.Readback = openshell.EffectiveReadback{Backend: openshell.BackendName, Revision: rec.BackendRevision, VerifiedAt: time.Now().UTC().Format(time.RFC3339), EvidenceID: openshellExecEvidenceID(reserveStatus.ReservationReceiptID)}
		if !result.Report.Passed {
			err = fmt.Errorf("openshell_readback_failed")
		}
	}
	actorID := strings.TrimSpace(body.AgentID)
	if actorID == "" {
		actorID = "openshell-session-executor"
	}
	binding := openshellExecBinding{
		ActionID:          reserveStatus.ActionID,
		DecisionReceiptID: reserveStatus.DecisionReceiptID,
		ReservationHash:   s.chainReceiptHash(reserveStatus.ReservationReceiptID),
		Target:            body.Target,
		Receipt:           result.Receipt,
		ActorID:           actorID,
		Plan:              body,
	}
	if result.Receipt.OperationID != "" && result.Receipt.BackendRevision != "" {
		s.osExecPutBinding(reserveStatus.ReservationReceiptID, binding)
	}
	if err != nil {
		var conflict *openshell.RevisionConflict
		if errors.As(err, &conflict) {
			// CAS pre-write rejection: provably no write from this
			// operation. Reconcile not_occurred and refuse.
			recStatus, recErr := s.reconcileUncertainExecution(reserveStatus, actorID, receipt.HoldExecutionNotOccurred)
			writeJSON(w, http.StatusConflict, map[string]any{
				"error": "revision_conflict", "reason_code": "revision_conflict",
				"expected_revision": conflict.Expected, "actual_revision": conflict.Actual,
				"execution":      receipt.HoldExecutionNotOccurred,
				"reservation":    reserveStatus,
				"reconciliation": recStatus,
				"note":           reconcileNote(recErr),
			})
			return
		}
		if result.Receipt.BackendRevision != "" {
			// The write reached the gateway but verification failed:
			// side effect occurred, outcome uncertain. Never rewrite
			// this as "not executed"; never auto-replay.
			evidencePersisted := s.recordUncertainExecution(reserveStatus, body.Target, result.Receipt, actorID)
			writeJSON(w, http.StatusConflict, map[string]any{
				"error": sanitizeOpenshellErr(err), "reason_code": "execution_uncertain",
				"execution_uncertain": true, "binding_evidence_persisted": evidencePersisted, "scope": "policy_apply", "task_executed": false,
				"reservation":        reserveStatus,
				"receipt":            result.Receipt,
				"report":             result.Report,
				"effective_readback": result.Readback,
				"note":               "副作用已发生且结果不确定；预留保持未决，等待管理员对账，不会自动重放",
			})
			return
		}
		// Transport/other failure: unknown whether any write happened.
		evidencePersisted := s.recordUncertainExecution(reserveStatus, body.Target, result.Receipt, actorID)
		writeJSON(w, http.StatusBadGateway, map[string]any{
			"error": sanitizeOpenshellErr(err), "reason_code": "execution_uncertain",
			"execution_uncertain": true, "binding_evidence_persisted": evidencePersisted, "scope": "policy_apply", "task_executed": false,
			"reservation": reserveStatus,
			"note":        "执行结果未知；预留保持未决，等待管理员对账，不会自动重放",
		})
		return
	}
	evID := openshellExecEvidenceID(reserveStatus.ReservationReceiptID)
	evDoc := map[string]any{
		"kind": "openshell_session_execution_binding", "reservation_receipt_id": reserveStatus.ReservationReceiptID,
		"action_id": binding.ActionID, "decision_receipt_id": binding.DecisionReceiptID,
		"target": body.Target, "operation_id": result.Receipt.OperationID,
		"backend_revision": result.Receipt.BackendRevision, "policy_digest": result.Receipt.AppliedPolicyDigest,
		"verify_level": result.Report.Level, "readback_evidence_id": result.Readback.EvidenceID,
		"endpoints": endpoints, "actor_id": actorID,
	}
	bindingPersisted := true
	if err := s.d.Store.PutEvidence(evID, evDoc); err != nil {
		// Reported honestly in the response instead of silently dropped.
		bindingPersisted = false
	}
	auditErr := s.d.Store.AppendAudit(state.AuditEvent{
		At: time.Now().UTC().Format(time.RFC3339), Event: "openshell_session_execution", Target: body.Target,
		Note: "operation=" + result.Receipt.OperationID + " reservation=" + reserveStatus.ReservationReceiptID,
	})
	if !bindingPersisted || auditErr != nil {
		writeJSON(w, 503, map[string]any{"ok": false, "error": "execution_evidence_incomplete", "scope": "policy_apply", "task_executed": false, "policy_applied": true, "reservation": reserveStatus})
		return
	}
	// Step ⑥ result correlation: the observation carries the reservation
	// identity so the signed result links task/session/tool call/
	// reservation/decision/target/policy revision.
	summary, _ := json.Marshal(evDoc)
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
	resp := map[string]any{
		"ok": obsErr == nil, "scope": "policy_apply", "task_executed": false, "reservation": reserveStatus,
		"receipt": result.Receipt, "report": result.Report, "effective_readback": result.Readback,
		"operation_id": result.Receipt.OperationID, "binding_evidence_id": evID,
		"binding_evidence_persisted": bindingPersisted,
		"target":                     body.Target,
	}
	if obsErr != nil {
		resp["observation_error"] = sanitizeOpenshellErr(obsErr)
		writeJSON(w, 503, resp)
		return
	} else {
		resp["observation_receipt_id"] = obs.ReceiptID
	}
	writeJSON(w, http.StatusOK, resp)
}

func (s *Server) recordUncertainExecution(reserveStatus *receipt.HoldExecutionStatus, target string, rec openshell.DeploymentReceipt, actorID string) bool {
	evID := openshellExecEvidenceID(reserveStatus.ReservationReceiptID)
	doc := map[string]any{
		"kind": "openshell_session_execution_uncertain", "reservation_receipt_id": reserveStatus.ReservationReceiptID,
		"action_id": reserveStatus.ActionID, "decision_receipt_id": reserveStatus.DecisionReceiptID,
		"target": target, "operation_id": rec.OperationID, "backend_revision": rec.BackendRevision,
		"actor_id": actorID,
	}
	evidenceErr := s.d.Store.PutEvidence(evID, doc)
	auditErr := s.d.Store.AppendAudit(state.AuditEvent{
		At: time.Now().UTC().Format(time.RFC3339), Event: "openshell_session_execution_uncertain", Target: target,
		Note: "reservation=" + reserveStatus.ReservationReceiptID,
	})
	return evidenceErr == nil && auditErr == nil
}

func reconcileNote(recErr string) string {
	if recErr == "" {
		return ""
	}
	return "自动对账未完成，预留仍需管理员处理: " + recErr
}

type openshellSessionPreviewRequest struct {
	Target string `json:"target"`
}

// Step ① preview: read-only view of what an execution WOULD be allowed to
// change. No execution, no permission expansion, no confirmation consumption.
func (s *Server) openshellSessionPreview(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST required"})
		return
	}
	var body openshellSessionPreviewRequest
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
		"target": body.Target, "grant_ids": grantIDs, "authorized_endpoints": authorized,
		// Contract honesty: the preview shows intent, it never proves the
		// gateway will actually enforce these limits at execution time.
		"execution_constraints_verified": false, "scope": "policy_apply", "task_executed": false,
		"note": "预览汇总当前有效授权；实际下发必须绑定单个 Grant 与完整批准参数，未验证任务执行限制",
	}
	if snap, err := s.d.Openshell.ReadEffective(body.Target); err != nil {
		resp["live_error"] = sanitizeOpenshellErr(err)
	} else {
		resp["live"] = map[string]any{
			"revision": snap.Revision, "policy_digest": snap.PolicyDigest,
			"endpoints": networkEndpoints(snap.Network),
		}
	}
	writeJSON(w, http.StatusOK, resp)
}

// canonicalRevision mirrors the openshell client's fail-closed revision shape
// so malformed input is rejected before the approval is consumed.
func canonicalRevision(revision string) bool {
	if revision == "" || revision[0] == '0' {
		return false
	}
	for _, r := range revision {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func networkEndpoints(rules []openshell.NetworkRule) []string {
	out := make([]string, 0, len(rules))
	for _, r := range rules {
		out = append(out, r.Endpoint)
	}
	sort.Strings(out)
	return out
}

type openshellSessionRollbackRequest struct {
	ReservationReceiptID string `json:"reservation_receipt_id"`
	ActionID             string `json:"action_id"`
	DecisionReceiptID    string `json:"decision_receipt_id"`
	ActorID              string `json:"actor_id"`
}

// Step ⑤/③ rollback: an administrator may only restore an operation this
// process executed and that still maps to the same reservation identity. The
// openshell client fails closed on unknown/consumed operations or drift.
func (s *Server) openshellSessionRollback(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST required"})
		return
	}
	var body openshellSessionRollbackRequest
	if err := readJSONStrict(r, &body, 4<<10); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid json"})
		return
	}
	if body.ReservationReceiptID == "" || body.ActionID == "" || body.DecisionReceiptID == "" || strings.TrimSpace(body.ActorID) == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "reservation_receipt_id, action_id, decision_receipt_id and actor_id are required"})
		return
	}
	if !s.openshellExecL3Gate(w) {
		return
	}
	binding, ok := s.osExecBindingFor(body.ReservationReceiptID)
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "no recorded openshell execution for this reservation"})
		return
	}
	if binding.ActionID != body.ActionID || binding.DecisionReceiptID != body.DecisionReceiptID {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "rollback identity does not match the recorded execution"})
		return
	}
	rb, err := s.d.Openshell.RollbackAuthorized(binding.Target, binding.Receipt, s.osExecRollbackAuthorizer(body.ReservationReceiptID, binding))
	if err != nil {
		// Fail-closed: the reservation stays unresolved; an admin must
		// reconcile after checking the external system.
		writeJSON(w, http.StatusConflict, map[string]any{
			"error": sanitizeOpenshellErr(err), "reason_code": "rollback_refused",
			"reservation_receipt_id": body.ReservationReceiptID,
			"note":                   "回滚被拒绝（fail-closed）；预留保持未决，等待管理员对账",
		})
		return
	}
	outcome := receipt.HoldExecutionOccurred
	if rb.Result == "no_op" {
		outcome = receipt.HoldExecutionNotOccurred
	}
	// A successful execution already has a signed observation, so
	// reconciliation is refused there (hold_reconciliation_changed_or_resolved)
	// and the rollback receipt itself is the durable restore record. An
	// uncertain execution has no observation, so the rollback finding closes it.
	var reconciliation *receipt.HoldExecutionStatus
	var reconcileErr string
	if status, rerr := s.reconcileUncertainExecution(&receipt.HoldExecutionStatus{
		ActionID: binding.ActionID, DecisionReceiptID: binding.DecisionReceiptID,
		ReservationReceiptID: body.ReservationReceiptID,
	}, body.ActorID, outcome); rerr != "" {
		reconcileErr = rerr
	} else {
		reconciliation = status
	}
	sum := sha256.Sum256([]byte("osr|" + body.ReservationReceiptID))
	evID := "osr-" + hex.EncodeToString(sum[:8])
	persistErr := s.d.Store.PutEvidence(evID, map[string]any{
		"kind": "openshell_session_execution_rollback", "reservation_receipt_id": body.ReservationReceiptID,
		"action_id": binding.ActionID, "target": binding.Target,
		"restored_revision": rb.RestoredRevision, "restored_digest": rb.RestoredDigest,
		"result": rb.Result, "actor_id": body.ActorID,
	})
	auditErr := s.d.Store.AppendAudit(state.AuditEvent{
		At: time.Now().UTC().Format(time.RFC3339), Event: "openshell_session_execution_rollback", Target: binding.Target,
		Note: "reservation=" + body.ReservationReceiptID + " result=" + rb.Result,
	})
	resp := map[string]any{
		"ok": persistErr == nil && auditErr == nil, "scope": "policy_apply", "task_executed": false, "rollback": rb, "outcome": outcome,
		"target": binding.Target, "evidence_id": evID,
	}
	if persistErr != nil || auditErr != nil {
		resp["error"] = "rollback_evidence_incomplete"
		writeJSON(w, 503, resp)
		return
	}
	if reconciliation != nil {
		resp["reconciliation"] = reconciliation
	}
	if reconcileErr != "" {
		resp["reconciliation_note"] = reconcileErr
	}
	writeJSON(w, http.StatusOK, resp)
}

// osExecRollbackAuthorizer revalidates, immediately before the restore write,
// that the reservation still exists in the signed chain with the same hash and
// identity, and that no reconciliation has already closed it.
func (s *Server) osExecRollbackAuthorizer(reservationReceiptID string, binding openshellExecBinding) openshell.RollbackAuthorizer {
	return func(authz openshell.RollbackAuthorization) error {
		if authz.Target != binding.Target || authz.OperationID != binding.Receipt.OperationID || authz.Restore.PolicyDigest != binding.Receipt.BasePolicyDigest {
			return fmt.Errorf("rollback target mismatch")
		}
		g, err := s.validateOpenShellExecutionBinding(binding.Plan)
		if err != nil {
			return err
		}
		allowed := grantNetwork(*g)
		bins := map[string]bool{}
		for _, p := range binding.Plan.BinaryPaths {
			bins[p] = true
		}
		for _, rule := range authz.Restore.Network {
			if rule.Effect != "allow" || !allowed[rule.Endpoint] {
				return fmt.Errorf("restore_network_not_authorized")
			}
			for _, p := range rule.BinaryPaths {
				if !bins[p] {
					return fmt.Errorf("restore_binary_not_authorized")
				}
			}
		}
		receipts, err := s.d.Chain.Read()
		if err != nil || receipt.Verify(receipts, s.d.Key.Public()) != nil {
			return fmt.Errorf("chain unreadable")
		}
		found := false
		for _, rec := range receipts {
			switch rec.ReceiptID {
			case reservationReceiptID:
				if rec.Hash != binding.ReservationHash {
					return fmt.Errorf("reservation hash mismatch")
				}
				found = true
			case reservationReceiptID + "-rec":
				return fmt.Errorf("reservation already reconciled")
			}
		}
		if !found {
			return fmt.Errorf("reservation missing from signed chain")
		}
		return nil
	}
}
