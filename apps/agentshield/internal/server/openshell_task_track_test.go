package server

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/openshell"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

// Server-side tests for the task tracking, stop and reconciliation routes.
//
// Every case below drives the production handlers. The task runner seam is the
// only injected component; the projection, the ownership checks, the ordering
// around the stop record and the refusal to claim a remote stop are all decided
// by production code.
//
// The fault cases deliberately damage test-created state (evidence files and an
// already-signed chain line) to prove the read paths degrade to an explicit,
// non-replaying verdict instead of guessing.

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

// newTaskRunnerServer mirrors newTaskExecServer but takes the task runner
// directly. taskSpy's next() callback receives no context, so a runner that has
// to observe cancellation cannot be expressed through it.
func newTaskRunnerServer(t *testing.T, runner openshell.TaskRunner) *Server {
	t.Helper()
	s, _ := newTaskExecServer(t, &taskSpy{})
	// Preserve the confirmed policy load on this Client while changing only
	// the process runner seam used by cancellation tests.
	s.d.Openshell.TaskRunner = runner
	return s
}

// taskTrackRun reserves and really executes one task through the production
// execute handler, then returns the server, the held decision and the
// reservation receipt id.
func taskTrackRun(t *testing.T, spy *taskSpy) (*Server, map[string]any, string) {
	t.Helper()
	s, _ := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)
	code, out := taskExecPost(t, s, token, taskExecBody(decision))
	if code != 200 || out["ok"] != true {
		t.Fatalf("fixture execution must succeed: HTTP %d %v", code, out)
	}
	res := out["reservation"].(map[string]any)
	id, _ := res["reservation_receipt_id"].(string)
	if id == "" {
		t.Fatalf("fixture execution returned no reservation id: %v", out)
	}
	return s, decision, id
}

// taskTrackReserve approves one execution and derives its reservation receipt
// id the way the engine derives it: the decision receipt id plus "-exec".
//
// The reservation itself is written by the execute route, not by the approval,
// so the derived id only becomes checkable once the caller has posted the
// execution. Callers therefore assert it with taskTrackReservationRecord after
// their own POST, instead of this helper asserting it against an empty chain.
func taskTrackReserve(t *testing.T, spy *taskSpy) (*Server, map[string]any, string) {
	t.Helper()
	s, _ := newTaskExecServer(t, spy)
	decision := taskExecApproveHold(t, s)
	reservationID := decision["receipt_id"].(string) + "-exec"
	return s, decision, reservationID
}

// taskTrackReservationRecord asserts that the derived reservation id names a
// real signed record bound to the approval, so a fixture that silently stopped
// matching production fails here rather than producing a passing test about the
// wrong record. It must run after the execute POST that writes the reservation.
func taskTrackReservationRecord(t *testing.T, s *Server, decision map[string]any, reservationID string) {
	t.Helper()
	taskTrackChainTaskID(t, s, reservationID)
	recs, err := s.d.Chain.Read()
	if err != nil {
		t.Fatalf("read chain: %v", err)
	}
	for _, rec := range recs {
		if rec.ReceiptID != reservationID {
			continue
		}
		if rec.DecisionReceiptID != str(decision["receipt_id"]) {
			t.Fatalf("reservation %s is not bound to approval %v", reservationID, decision["receipt_id"])
		}
		if rec.RecordType != openshellTaskReservationRecord {
			t.Fatalf("reservation %s record type = %q, want %q", reservationID, rec.RecordType, openshellTaskReservationRecord)
		}
		return
	}
}

func taskTrackStatus(t *testing.T, s *Server, bearer string, body any) (int, map[string]any) {
	t.Helper()
	return sessionExecPost(t, s, "/v1/openshell/task-executions/status", bearer, body)
}

func taskTrackStop(t *testing.T, s *Server, bearer string, body any) (int, map[string]any) {
	t.Helper()
	return sessionExecPost(t, s, "/v1/openshell/task-executions/stop", bearer, body)
}

func taskTrackReconcile(t *testing.T, s *Server, bearer string, body any) (int, map[string]any) {
	t.Helper()
	return sessionExecPost(t, s, "/v1/openshell/task-executions/reconcile", bearer, body)
}

func taskTrackRead(t *testing.T, s *Server, bearer string, body any) (int, map[string]any) {
	t.Helper()
	return sessionExecPost(t, s, "/v1/openshell/task-executions/read", bearer, body)
}

// taskTrackChainLen counts the signed lines so a test can state "this route
// wrote nothing" as a fact about durable state rather than about a response.
func taskTrackChainLen(t *testing.T, s *Server) int {
	t.Helper()
	recs, err := s.d.Chain.Read()
	if err != nil {
		t.Fatalf("read chain: %v", err)
	}
	return len(recs)
}

// taskTrackStatusBody deliberately omits task_id and runtime_task_id. That is
// exactly what the production execute route itself submits, and it is the shape
// that must keep working.
func taskTrackStatusBody(reservationID string, decision map[string]any) map[string]any {
	return map[string]any{
		"schema_version":         openshellTaskStatusReqSchema,
		"platform":               "openclaw",
		"session_id":             "hold-session",
		"agent_id":               taskExecTarget(),
		"tool":                   "exec",
		"action_id":              decision["action_id"],
		"decision_receipt_id":    decision["receipt_id"],
		"reservation_receipt_id": reservationID,
	}
}

func taskTrackStopBody(reservationID string, decision map[string]any) map[string]any {
	return map[string]any{
		"schema_version":         openshellTaskStopSchema,
		"reservation_receipt_id": reservationID,
		"action_id":              decision["action_id"],
		"decision_receipt_id":    decision["receipt_id"],
		"target":                 taskExecTarget(),
		"platform":               "openclaw",
		"session_id":             "hold-session",
		"agent_id":               taskExecTarget(),
		"tool":                   "exec",
		"actor_id":               "fixture-admin",
	}
}

func taskTrackReconcileBody(t *testing.T, s *Server, reservationID string, decision map[string]any, outcome string) map[string]any {
	t.Helper()
	hash := s.chainReceiptHash(reservationID)
	if !taskHex64(hash) {
		t.Fatalf("reservation %s has no verifiable chain hash", reservationID)
	}
	return map[string]any{
		"schema_version":         openshellTaskReconcileSchema,
		"reservation_receipt_id": reservationID,
		"reservation_hash":       hash,
		"action_id":              decision["action_id"],
		"decision_receipt_id":    decision["receipt_id"],
		"outcome":                outcome,
		"actor_id":               "fixture-admin",
		"evidence_note":          "fixture external verification",
	}
}

func taskTrackEvidencePath(s *Server, id string) string {
	return filepath.Join(s.d.Store.Dir, "evidence", id+".json")
}

func taskTrackRemoveEvidence(t *testing.T, s *Server, id string) {
	t.Helper()
	if err := os.Remove(taskTrackEvidencePath(s, id)); err != nil {
		t.Fatalf("remove evidence %s: %v", id, err)
	}
}

func taskTrackRewritePlan(t *testing.T, s *Server, reservationID string, mutate func(map[string]any)) {
	t.Helper()
	path := taskTrackEvidencePath(s, openshellTaskPlanEvidenceID(reservationID))
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read plan evidence: %v", err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("plan evidence is not JSON: %v", err)
	}
	mutate(doc)
	// This fixture exercises a genuinely expired plan. Re-sign it as a valid
	// producer document; separate tests cover unauthenticated file mutation.
	if err := s.signTaskEvidence(doc); err != nil {
		t.Fatal(err)
	}
	out, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, out, 0o600); err != nil {
		t.Fatalf("rewrite plan evidence: %v", err)
	}
}

// taskTrackChainTaskID reads the signed reservation record so a test can state
// its precondition (the fixture submits no task identity) instead of assuming it.
func taskTrackChainTaskID(t *testing.T, s *Server, reservationID string) string {
	t.Helper()
	recs, err := s.d.Chain.Read()
	if err != nil {
		t.Fatalf("read chain: %v", err)
	}
	for _, rec := range recs {
		if rec.ReceiptID == reservationID {
			return rec.TaskID
		}
	}
	t.Fatalf("reservation %s is not in the chain", reservationID)
	return ""
}

// taskTrackTamperChain appends a copy of the newest signed line with one field
// changed. The line stays well-formed JSON with the original seq and hash, so
// Chain.Read parses it and only signature verification can tell that the
// content no longer matches what was signed. Nothing already on disk is
// modified or removed.
func taskTrackTamperChain(t *testing.T, s *Server) {
	t.Helper()
	paths, err := filepath.Glob(filepath.Join(s.d.Store.Dir, "receipts", "local", "*.jsonl"))
	if err != nil || len(paths) == 0 {
		t.Fatalf("chain file not found: %v (%v)", paths, err)
	}
	path := paths[len(paths)-1]
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read chain: %v", err)
	}
	lines := strings.Split(strings.TrimRight(string(raw), "\n"), "\n")
	last := lines[len(lines)-1]
	if strings.TrimSpace(last) == "" {
		t.Fatalf("chain file %s holds no signed line", path)
	}
	var doc map[string]any
	if err := json.Unmarshal([]byte(last), &doc); err != nil {
		t.Fatalf("chain line is not JSON: %v", err)
	}
	doc["receipt_id"] = "tampered-receipt"
	mutated, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		t.Fatalf("open chain for append: %v", err)
	}
	defer f.Close()
	if _, err := f.Write(append(mutated, '\n')); err != nil {
		t.Fatalf("append tampered line: %v", err)
	}
}

func mustKey(t *testing.T, doc map[string]any, key string) map[string]any {
	t.Helper()
	v, ok := doc[key].(map[string]any)
	if !ok {
		t.Fatalf("expected object at %q in %v", key, doc)
	}
	return v
}

// ---------------------------------------------------------------------------
// status: the happy path and what it refuses to disclose
// ---------------------------------------------------------------------------

func TestOpenShellTaskTrackStatusProjectsSignedRecordWithoutIdentity(t *testing.T) {
	spy := &taskSpy{}
	s, decision, reservationID := taskTrackRun(t, spy)

	// Precondition: the fixture submits no task identity, so the signed
	// reservation carries none. The status contract does not require one.
	if got := taskTrackChainTaskID(t, s, reservationID); got != "" {
		t.Fatalf("fixture precondition: chain task id = %q, want empty", got)
	}

	code, doc := taskTrackStatus(t, s, token, taskTrackStatusBody(reservationID, decision))
	if code != 200 {
		t.Fatalf("status without task identity: HTTP %d %v", code, doc)
	}
	if doc["state"] != openshell.TaskStateSucceeded {
		t.Fatalf("state = %v, want %v (%v)", doc["state"], openshell.TaskStateSucceeded, doc)
	}
	if doc["task_execution_kind"] != "real_sandbox_command" {
		t.Fatalf("kind = %v, want real_sandbox_command", doc["task_execution_kind"])
	}
	// Remote success is reported by the exit code the backend returned, not by
	// a bare "executed" flag: the projection never claims a task ran, it only
	// reports what the recorded outcome says.
	if exit, ok := doc["remote_exit_code"].(float64); !ok || exit != 0 {
		t.Fatalf("remote_exit_code = %v, want 0 (%v)", doc["remote_exit_code"], doc)
	}
	if _, present := doc["task_executed"]; present {
		t.Fatalf("status invented an executed flag instead of the recorded exit: %v", doc)
	}
	if _, present := doc["task_id"]; present {
		t.Fatalf("status invented a task identity: %v", doc)
	}
	if _, present := doc["runtime_task_id"]; present {
		t.Fatalf("status invented a runtime task identity: %v", doc)
	}
	if !taskHex64(str(doc["argv_digest"])) {
		t.Fatalf("argv_digest = %v, want a 64-hex digest", doc["argv_digest"])
	}

	output := mustKey(t, doc, "output")
	if output["raw_stored"] != false || output["raw_opt_in"] != false {
		t.Fatalf("output must stay a redacted digest by default: %v", output)
	}
	if !taskHex64(str(output["digest"])) {
		t.Fatalf("output digest = %v, want 64-hex", output["digest"])
	}

	// The raw argv must not leak through any field of the projection.
	encoded, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	for _, arg := range taskExecArgv {
		if strings.Contains(string(encoded), arg) {
			t.Fatalf("projection leaked raw argv %q: %s", arg, encoded)
		}
	}

	// Reading is not a side effect: repeated reads must not re-run anything.
	if spy.callCount() != 1 {
		t.Fatalf("runner calls after execution = %d, want 1", spy.callCount())
	}
	if code2, doc2 := taskTrackStatus(t, s, token, taskTrackStatusBody(reservationID, decision)); code2 != 200 || doc2["state"] != openshell.TaskStateSucceeded {
		t.Fatalf("repeat status read: HTTP %d %v", code2, doc2)
	}
	if spy.callCount() != 1 {
		t.Fatalf("re-reading status replayed the task: %d runner calls", spy.callCount())
	}
}

func str(v any) string {
	s, _ := v.(string)
	return s
}

func TestOpenShellTaskTrackStatusRejectsBadShapeAndForeignIdentity(t *testing.T) {
	spy := &taskSpy{}
	s, decision, reservationID := taskTrackRun(t, spy)

	cases := []struct {
		name    string
		bearer  string
		mutate  func(map[string]any)
		want    int
		wantErr string
	}{
		{
			name:   "no credential",
			bearer: "",
			want:   401,
		},
		{
			// The admin credential is a different capability class; it must not
			// be accepted on a decision-shaped route.
			name:   "admin credential",
			bearer: s.bootAdmin,
			want:   401,
		},
		{
			name:    "foreign agent",
			bearer:  token,
			mutate:  func(b map[string]any) { b["agent_id"] = "inst_2" },
			want:    404,
			wantErr: "openshell_task_reservation_mismatch",
		},
		{
			name:    "foreign decision receipt",
			bearer:  token,
			mutate:  func(b map[string]any) { b["decision_receipt_id"] = "dec_other" },
			want:    404,
			wantErr: "openshell_task_reservation_mismatch",
		},
		{
			name:    "unsupported tool",
			bearer:  token,
			mutate:  func(b map[string]any) { b["tool"] = "read" },
			want:    400,
			wantErr: "invalid_openshell_task_status_shape",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			body := taskTrackStatusBody(reservationID, decision)
			if tc.mutate != nil {
				tc.mutate(body)
			}
			code, out := taskTrackStatus(t, s, tc.bearer, body)
			if code != tc.want {
				t.Fatalf("HTTP %d, want %d: %v", code, tc.want, out)
			}
			if tc.wantErr != "" && str(out["error"]) != tc.wantErr {
				t.Fatalf("error = %v, want %s", out["error"], tc.wantErr)
			}
		})
	}

	t.Run("wrong method", func(t *testing.T) {
		req := loopbackRequest("GET", "/v1/openshell/task-executions/status", nil)
		req.Header.Set("Authorization", "Bearer "+token)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, req)
		if w.Code != 405 {
			t.Fatalf("GET status: HTTP %d, want 405", w.Code)
		}
	})

	t.Run("unknown reservation", func(t *testing.T) {
		code, out := taskTrackStatus(t, s, token, taskTrackStatusBody("hold-unknown-exec", decision))
		if code != 404 || str(out["error"]) != "openshell_task_reservation_unknown" {
			t.Fatalf("HTTP %d %v", code, out)
		}
	})
}

// ---------------------------------------------------------------------------
// status: recovery projection is derived from what is on disk, and only reads
// ---------------------------------------------------------------------------

func TestOpenShellTaskTrackRecoveryProjectionReadsWithoutReplaying(t *testing.T) {
	t.Run("no launch marker and no outcome", func(t *testing.T) {
		spy := &taskSpy{}
		s, decision, reservationID := taskTrackRun(t, spy)
		taskTrackRemoveEvidence(t, s, openshellTaskStartEvidenceID(reservationID))
		taskTrackRemoveEvidence(t, s, openshellTaskEvidenceID(reservationID))

		code, doc := taskTrackStatus(t, s, token, taskTrackStatusBody(reservationID, decision))
		if code != 200 {
			t.Fatalf("HTTP %d %v", code, doc)
		}
		if doc["state"] != "reserved" || str(doc["reason_code"]) != "openshell_task_reserved" {
			t.Fatalf("state = %v reason = %v, want reserved", doc["state"], doc["reason_code"])
		}
		if spy.callCount() != 1 {
			t.Fatalf("recovery projection re-ran the task: %d runner calls", spy.callCount())
		}
	})

	t.Run("launch marker without an outcome", func(t *testing.T) {
		spy := &taskSpy{}
		s, decision, reservationID := taskTrackRun(t, spy)
		taskTrackRemoveEvidence(t, s, openshellTaskEvidenceID(reservationID))

		code, doc := taskTrackStatus(t, s, token, taskTrackStatusBody(reservationID, decision))
		if code != 200 {
			t.Fatalf("HTTP %d %v", code, doc)
		}
		// The process is gone: a launch marker alone never proves the task is
		// still running, nor that it finished.
		if doc["state"] != "uncertain" || str(doc["reason_code"]) != "openshell_task_result_uncertain" {
			t.Fatalf("state = %v reason = %v, want uncertain", doc["state"], doc["reason_code"])
		}
		if spy.callCount() != 1 {
			t.Fatalf("uncertain recovery re-ran the task: %d runner calls", spy.callCount())
		}
	})

	t.Run("expired reservation with no launch", func(t *testing.T) {
		spy := &taskSpy{}
		s, decision, reservationID := taskTrackRun(t, spy)
		taskTrackRemoveEvidence(t, s, openshellTaskStartEvidenceID(reservationID))
		taskTrackRemoveEvidence(t, s, openshellTaskEvidenceID(reservationID))
		taskTrackRewritePlan(t, s, reservationID, func(doc map[string]any) {
			doc["reservation_expires_at"] = time.Now().Add(-time.Hour).UTC().Format(time.RFC3339Nano)
		})

		code, doc := taskTrackStatus(t, s, token, taskTrackStatusBody(reservationID, decision))
		if code != 200 {
			t.Fatalf("HTTP %d %v", code, doc)
		}
		if doc["state"] != "denied" || str(doc["reason_code"]) != "openshell_task_reservation_expired" {
			t.Fatalf("state = %v reason = %v, want denied/expired", doc["state"], doc["reason_code"])
		}
	})

	t.Run("unreadable outcome", func(t *testing.T) {
		spy := &taskSpy{}
		s, decision, reservationID := taskTrackRun(t, spy)
		if err := os.WriteFile(taskTrackEvidencePath(s, openshellTaskEvidenceID(reservationID)), []byte("{not json"), 0o600); err != nil {
			t.Fatal(err)
		}
		code, out := taskTrackStatus(t, s, token, taskTrackStatusBody(reservationID, decision))
		if code != 503 || str(out["error"]) != "task_evidence_unreadable" {
			t.Fatalf("HTTP %d %v, want 503 task_evidence_unreadable", code, out)
		}
		if spy.callCount() != 1 {
			t.Fatalf("unreadable evidence triggered a re-run: %d runner calls", spy.callCount())
		}
	})
}

func TestOpenShellTaskTrackTamperedChainIsRefused(t *testing.T) {
	spy := &taskSpy{}
	s, decision, reservationID := taskTrackRun(t, spy)
	statusBody := taskTrackStatusBody(reservationID, decision)

	// Control: the untouched chain verifies and the read succeeds.
	if code, doc := taskTrackStatus(t, s, token, statusBody); code != 200 {
		t.Fatalf("control status read: HTTP %d %v", code, doc)
	}
	// The reconciliation hash can only be read while the chain still verifies,
	// so the request is built before the tamper and only sent after it.
	reconcileBody := taskTrackReconcileBody(t, s, reservationID, decision, receipt.HoldExecutionNotOccurred)
	stopBody := taskTrackStopBody(reservationID, decision)

	taskTrackTamperChain(t, s)

	cases := []struct {
		name string
		call func() (int, map[string]any)
	}{
		{"status", func() (int, map[string]any) {
			return taskTrackStatus(t, s, token, statusBody)
		}},
		{"stop", func() (int, map[string]any) {
			return taskTrackStop(t, s, token, stopBody)
		}},
		{"reconcile", func() (int, map[string]any) {
			return taskTrackReconcile(t, s, s.bootAdmin, reconcileBody)
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			code, out := tc.call()
			if code != 503 {
				t.Fatalf("HTTP %d %v, want 503 once the chain fails verification", code, out)
			}
			if errCode := str(out["error"]); errCode != "openshell_chain_unverified" {
				t.Fatalf("error = %v, want openshell_chain_unverified", errCode)
			}
			if _, ok := out["reservation"]; ok {
				t.Fatalf("a refused read must not present reservation facts: %v", out)
			}
		})
	}
}

func TestOpenShellTaskTrackRejectsForgedOutcomeFile(t *testing.T) {
	spy := &taskSpy{next: func(int) openshell.TaskRunResult {
		return openshell.TaskRunResult{ExitCode: 3, Stdout: "failed\n", Spawned: true}
	}}
	s, decision, reservationID := taskTrackReserve(t, spy)
	code, out := taskExecPost(t, s, token, taskExecBody(decision))
	if code != 502 || str(out["error"]) != "task_failed" {
		t.Fatalf("fixture failure: HTTP %d %v", code, out)
	}
	path := taskTrackEvidencePath(s, openshellTaskEvidenceID(reservationID))
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	// All fields stay well-formed. Before evidence authentication this editable
	// file alone would have made /status report a remote success.
	doc["state"] = "succeeded"
	doc["exit_code"] = 0
	forged, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, forged, 0o600); err != nil {
		t.Fatal(err)
	}
	for _, view := range []struct {
		name   string
		bearer string
		read   func(*testing.T, *Server, string, any) (int, map[string]any)
	}{
		{"decision_status", token, taskTrackStatus},
		{"admin_read", s.bootAdmin, taskTrackRead},
	} {
		t.Run(view.name, func(t *testing.T) {
			code, result := view.read(t, s, view.bearer, taskTrackStatusBody(reservationID, decision))
			if code != 503 || str(result["error"]) != "task_evidence_unverified" {
				t.Fatalf("forged success was not rejected: HTTP %d %v", code, result)
			}
		})
	}
	if spy.callCount() != 1 {
		t.Fatalf("tampered status replayed the task: %d runner calls", spy.callCount())
	}
}

func TestOpenShellTaskTrackRejectsUnsignedPlanAndStart(t *testing.T) {
	for _, tc := range []struct {
		name string
		id   func(string) string
	}{
		{"plan", openshellTaskPlanEvidenceID},
		{"start", openshellTaskStartEvidenceID},
	} {
		t.Run(tc.name, func(t *testing.T) {
			spy := &taskSpy{}
			s, decision, reservationID := taskTrackRun(t, spy)
			path := taskTrackEvidencePath(s, tc.id(reservationID))
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			var doc map[string]any
			if err := json.Unmarshal(raw, &doc); err != nil {
				t.Fatal(err)
			}
			delete(doc, "signature")
			changed, err := json.Marshal(doc)
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, changed, 0o600); err != nil {
				t.Fatal(err)
			}
			code, result := taskTrackStatus(t, s, token, taskTrackStatusBody(reservationID, decision))
			if code != 503 || str(result["error"]) != "task_evidence_unverified" {
				t.Fatalf("unsigned %s was not rejected: HTTP %d %v", tc.name, code, result)
			}
			if spy.callCount() != 1 {
				t.Fatalf("unsigned %s replayed the task", tc.name)
			}
		})
	}
}

func TestOpenShellTaskTrackSuccessRequiresMatchingSignedObservation(t *testing.T) {
	spy := &taskSpy{}
	s, _, reservationID := taskTrackRun(t, spy)
	facts, code := s.taskChainFacts(reservationID)
	if code != "" {
		t.Fatalf("verified chain facts: %s", code)
	}
	doc, err := s.d.Store.GetEvidence(openshellTaskEvidenceID(reservationID))
	if err != nil || !facts.matchesObservedOutcome(doc) {
		t.Fatalf("successful outcome lacks matching signed observation: %v", err)
	}
	withoutObservation := *facts
	withoutObservation.Observation = nil
	if withoutObservation.matchesObservedOutcome(doc) {
		t.Fatal("local success without a signed observation was accepted")
	}
	changed := make(map[string]any, len(doc))
	for key, value := range doc {
		changed[key] = value
	}
	changed["stdout_digest"] = strings.Repeat("0", 64)
	if facts.matchesObservedOutcome(changed) {
		t.Fatal("observation was accepted for a different outcome document")
	}
}

func TestOpenShellTaskTrackRejectsUnsignedStopRecord(t *testing.T) {
	spy := &taskSpy{}
	s, decision, reservationID := taskTrackRun(t, spy)
	code, out := taskTrackStop(t, s, token, taskTrackStopBody(reservationID, decision))
	if code != 409 || str(out["error"]) != "stop_not_observable" {
		t.Fatalf("fixture stop record: HTTP %d %v", code, out)
	}
	path := taskTrackEvidencePath(s, openshellTaskStopEvidenceID(reservationID))
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	delete(doc, "signature")
	changed, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, changed, 0o600); err != nil {
		t.Fatal(err)
	}
	code, out = taskTrackStatus(t, s, token, taskTrackStatusBody(reservationID, decision))
	if code != 503 || str(out["error"]) != "task_evidence_unverified" {
		t.Fatalf("unsigned stop record was not rejected: HTTP %d %v", code, out)
	}
	if spy.callCount() != 1 {
		t.Fatalf("unsigned stop record replayed the task: %d", spy.callCount())
	}
}

// ---------------------------------------------------------------------------
// stop
// ---------------------------------------------------------------------------

func TestOpenShellTaskStopNeverClaimsRemoteTermination(t *testing.T) {
	// A task that already finished: the local process is gone, so no
	// termination can be issued, and the route must say so rather than pretend
	// the remote sandbox was stopped.
	spy := &taskSpy{}
	s, decision, reservationID := taskTrackRun(t, spy)
	if got := taskTrackChainTaskID(t, s, reservationID); got != "" {
		t.Fatalf("fixture precondition: chain task id = %q, want empty", got)
	}

	code, out := taskTrackStop(t, s, token, taskTrackStopBody(reservationID, decision))
	if code == 403 {
		t.Fatalf("stop rejected an execution that carries no task identity: %v", out)
	}
	if code != 409 || str(out["error"]) != "stop_not_observable" {
		t.Fatalf("HTTP %d %v, want 409 stop_not_observable", code, out)
	}
	if out["remote_stopped"] != false {
		t.Fatalf("remote_stopped = %v, must be literally false", out["remote_stopped"])
	}
	if !strings.Contains(str(out["note"]), "本地未运行不等于远端任务已停止") {
		t.Fatalf("stop note must not imply the remote task stopped: %q", out["note"])
	}

	// The durable stop record is the evidence a later reader relies on.
	stopDoc := readEvidence(t, s, openshellTaskStopEvidenceID(reservationID))
	if stopDoc["remote_stop"] != "unsupported" {
		t.Fatalf("recorded remote_stop = %v, want unsupported", stopDoc["remote_stop"])
	}
	if stopDoc["remote_stop_confirmed"] != false {
		t.Fatalf("recorded remote_stop_confirmed = %v, want false", stopDoc["remote_stop_confirmed"])
	}
	if stopDoc["delete_sandbox"] != false {
		t.Fatalf("recorded delete_sandbox = %v, want false", stopDoc["delete_sandbox"])
	}
	if stopDoc["local_cli_termination"] != "not_running" {
		t.Fatalf("recorded local_cli_termination = %v, want not_running", stopDoc["local_cli_termination"])
	}
	if stopDoc["reservation_receipt_id"] != reservationID {
		t.Fatalf("stop record bound to %v, want %s", stopDoc["reservation_receipt_id"], reservationID)
	}
}

func TestOpenShellTaskStopRejectsBadShapeAndForeignIdentity(t *testing.T) {
	spy := &taskSpy{}
	s, decision, reservationID := taskTrackRun(t, spy)

	t.Run("foreign target", func(t *testing.T) {
		body := taskTrackStopBody(reservationID, decision)
		body["agent_id"] = "inst_2"
		code, out := taskTrackStop(t, s, token, body)
		if code != 403 || str(out["error"]) != "openshell_task_stop_identity_mismatch" {
			t.Fatalf("HTTP %d %v", code, out)
		}
	})

	t.Run("delete the sandbox instead of the task", func(t *testing.T) {
		body := taskTrackStopBody(reservationID, decision)
		body["delete_sandbox"] = true
		code, out := taskTrackStop(t, s, token, body)
		if code != 400 || str(out["error"]) != "invalid_openshell_task_stop_shape" {
			t.Fatalf("HTTP %d %v", code, out)
		}
		if _, err := os.Stat(taskTrackEvidencePath(s, openshellTaskStopEvidenceID(reservationID))); err == nil {
			t.Fatal("a rejected stop request must not persist a stop record")
		}
	})

	t.Run("wrong method", func(t *testing.T) {
		req := loopbackRequest("GET", "/v1/openshell/task-executions/stop", nil)
		req.Header.Set("Authorization", "Bearer "+token)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, req)
		if w.Code != 405 {
			t.Fatalf("GET stop: HTTP %d, want 405", w.Code)
		}
	})

	t.Run("no credential", func(t *testing.T) {
		code, out := taskTrackStop(t, s, "", taskTrackStopBody(reservationID, decision))
		if code != 401 {
			t.Fatalf("HTTP %d %v, want 401", code, out)
		}
	})

	t.Run("wrong credential class", func(t *testing.T) {
		code, out := taskTrackStop(t, s, s.bootAdmin, taskTrackStopBody(reservationID, decision))
		if code != 401 {
			t.Fatalf("HTTP %d %v, want 401", code, out)
		}
	})

	t.Run("unknown reservation", func(t *testing.T) {
		code, out := taskTrackStop(t, s, token, taskTrackStopBody("hold-unknown-exec", decision))
		if code != 404 || str(out["error"]) != "openshell_task_reservation_unknown" {
			t.Fatalf("HTTP %d %v", code, out)
		}
	})
}

// TestOpenShellTaskStopCancelsOnlyTheLocalObservation drives a stop into a
// genuinely running task. The runner blocks until its context is cancelled, so
// the stop route is exercised while the task is live. What the route may do is
// cancel the local CLI; what it may not do is claim the remote task stopped.
func TestOpenShellTaskStopCancelsOnlyTheLocalObservation(t *testing.T) {
	started := make(chan struct{})
	runner := func(ctx context.Context, args []string, timeout time.Duration, limit int) openshell.TaskRunResult {
		close(started)
		<-ctx.Done()
		return openshell.TaskRunResult{
			ExitCode:   -1,
			BoundFired: openshell.TaskBoundStop,
			Spawned:    true,
			Stderr:     "local cli terminated",
		}
	}
	s := newTaskRunnerServer(t, runner)
	decision := taskExecApproveHold(t, s)
	body := taskExecBody(decision)

	type execResult struct {
		code int
		out  map[string]any
	}
	done := make(chan execResult, 1)
	go func() {
		code, out := taskExecPost(t, s, token, body)
		done <- execResult{code, out}
	}()

	select {
	case <-started:
	case <-time.After(20 * time.Second):
		t.Fatal("the task never reached the runner")
	}

	var reservationID string
	select {
	case r := <-done:
		t.Fatalf("the task finished before the stop was issued: HTTP %d %v", r.code, r.out)
	default:
	}

	// Find the reservation id from the plan evidence the execute handler wrote
	// before spawning, without racing the execute goroutine's response.
	matches, err := filepath.Glob(filepath.Join(s.d.Store.Dir, "evidence", "ostp-*.json"))
	if err != nil || len(matches) != 1 {
		t.Fatalf("expected exactly one task plan evidence file, got %v (%v)", matches, err)
	}
	raw, err := os.ReadFile(matches[0])
	if err != nil {
		t.Fatal(err)
	}
	var plan map[string]any
	if err := json.Unmarshal(raw, &plan); err != nil {
		t.Fatal(err)
	}
	reservationID = str(plan["reservation_receipt_id"])
	if reservationID == "" {
		t.Fatalf("plan evidence carries no reservation id: %v", plan)
	}

	code, stopOut := taskTrackStop(t, s, token, taskTrackStopBody(reservationID, decision))
	if code != 200 {
		t.Fatalf("stop while observing: HTTP %d %v", code, stopOut)
	}
	if stopOut["state"] != "stop_requested" {
		t.Fatalf("state = %v, want stop_requested", stopOut["state"])
	}
	stopBlock := mustKey(t, stopOut, "stop")
	if stopBlock["local_cli_termination"] != "requested" {
		t.Fatalf("local_cli_termination = %v, want requested", stopBlock["local_cli_termination"])
	}
	if stopBlock["remote_stop"] != "unsupported" || stopBlock["remote_stop_confirmed"] != false {
		t.Fatalf("stop block overstates what was achieved: %v", stopBlock)
	}
	if !strings.Contains(str(stopBlock["note"]), "不等于远端任务已停止") {
		t.Fatalf("stop block must not imply the remote task stopped: %q", stopBlock["note"])
	}

	select {
	case r := <-done:
		if r.code != 502 {
			t.Fatalf("stopped-after-spawn execution: HTTP %d %v, want 502", r.code, r.out)
		}
		if str(r.out["error"]) != "execution_uncertain" {
			t.Fatalf("error = %v, want execution_uncertain", r.out["error"])
		}
		if str(r.out["reason_code"]) != "execution_stopped_after_spawn_uncertain" {
			t.Fatalf("reason_code = %v, want execution_stopped_after_spawn_uncertain", r.out["reason_code"])
		}
	case <-time.After(20 * time.Second):
		t.Fatal("the execute handler never returned after the stop")
	}
}

func TestOpenShellTaskStopBeforeSpawnReconcilesAsNotOccurred(t *testing.T) {
	spy := &taskSpy{next: func(int) openshell.TaskRunResult {
		return openshell.TaskRunResult{ExitCode: -1, BoundFired: openshell.TaskBoundStop, Spawned: false}
	}}
	s, decision, reservationID := taskTrackReserve(t, spy)
	code, out := taskExecPost(t, s, token, taskExecBody(decision))
	if code != 409 || str(out["error"]) != "execution_stopped_before_spawn" {
		t.Fatalf("HTTP %d %v, want 409 execution_stopped_before_spawn", code, out)
	}
	taskTrackReservationRecord(t, s, decision, reservationID)

	code, doc := taskTrackStatus(t, s, token, taskTrackStatusBody(reservationID, decision))
	if code != 200 {
		t.Fatalf("status: HTTP %d %v", code, doc)
	}
	if doc["state"] != "reconciled_not_occurred" {
		t.Fatalf("state = %v, want reconciled_not_occurred", doc["state"])
	}
	if str(doc["reason_code"]) != "openshell_task_confirmed_not_occurred" {
		t.Fatalf("reason_code = %v", doc["reason_code"])
	}
}

// ---------------------------------------------------------------------------
// reconcile
// ---------------------------------------------------------------------------

func TestOpenShellTaskReconcileRequiresAdminAndExactBinding(t *testing.T) {
	spy := &taskSpy{next: func(int) openshell.TaskRunResult {
		return openshell.TaskRunResult{ExitCode: 3, Stdout: "boom\n", Spawned: true}
	}}
	s, decision, reservationID := taskTrackReserve(t, spy)

	// A failing task leaves the reservation unresolved but observed-compatible:
	// the execute route returns without calling Observe, so the reservation is
	// still open for an administrator to close on external evidence.
	code, execOut := taskExecPost(t, s, token, taskExecBody(decision))
	if code != 502 || str(execOut["error"]) != "task_failed" {
		t.Fatalf("fixture execution: HTTP %d %v, want 502 task_failed", code, execOut)
	}
	if execOut["execution_uncertain"] != true {
		t.Fatalf("a failing task must stay uncertain: %v", execOut)
	}
	taskTrackReservationRecord(t, s, decision, reservationID)

	t.Run("decision credential cannot reconcile", func(t *testing.T) {
		code, out := taskTrackReconcile(t, s, token, taskTrackReconcileBody(t, s, reservationID, decision, receipt.HoldExecutionNotOccurred))
		if code != 403 {
			t.Fatalf("HTTP %d %v, want 403: a decision credential must not close a reservation", code, out)
		}
	})

	t.Run("wrong reservation hash", func(t *testing.T) {
		body := taskTrackReconcileBody(t, s, reservationID, decision, receipt.HoldExecutionNotOccurred)
		body["reservation_hash"] = strings.Repeat("0", 64)
		code, out := taskTrackReconcile(t, s, s.bootAdmin, body)
		if code != 409 || str(out["error"]) != "openshell_task_reconcile_hash_mismatch" {
			t.Fatalf("HTTP %d %v, want 409 hash mismatch", code, out)
		}
	})

	t.Run("foreign decision receipt", func(t *testing.T) {
		body := taskTrackReconcileBody(t, s, reservationID, decision, receipt.HoldExecutionNotOccurred)
		body["action_id"] = "other-action"
		code, out := taskTrackReconcile(t, s, s.bootAdmin, body)
		if code != 403 || str(out["error"]) != "openshell_task_reconcile_identity_mismatch" {
			t.Fatalf("HTTP %d %v, want 403 identity mismatch", code, out)
		}
	})

	t.Run("bad shape", func(t *testing.T) {
		body := taskTrackReconcileBody(t, s, reservationID, decision, receipt.HoldExecutionNotOccurred)
		body["reservation_hash"] = "not-a-digest"
		code, out := taskTrackReconcile(t, s, s.bootAdmin, body)
		if code != 400 || str(out["error"]) != "invalid_openshell_task_reconcile_shape" {
			t.Fatalf("HTTP %d %v, want 400", code, out)
		}
	})

	t.Run("unknown outcome", func(t *testing.T) {
		body := taskTrackReconcileBody(t, s, reservationID, decision, "probably")
		code, out := taskTrackReconcile(t, s, s.bootAdmin, body)
		if code != 400 || str(out["error"]) != "invalid_openshell_task_reconcile_shape" {
			t.Fatalf("HTTP %d %v, want 400", code, out)
		}
	})

	t.Run("resolved by external evidence and then closed", func(t *testing.T) {
		body := taskTrackReconcileBody(t, s, reservationID, decision, receipt.HoldExecutionNotOccurred)
		// A successful closure answers with the re-read projection, so the
		// caller sees the same document the status route would serve.
		code, out := taskTrackReconcile(t, s, s.bootAdmin, body)
		if code != 200 {
			t.Fatalf("HTTP %d %v, want 200", code, out)
		}
		if out["state"] != "reconciled_not_occurred" {
			t.Fatalf("state = %v, want reconciled_not_occurred (%v)", out["state"], out)
		}
		if str(out["reason_code"]) != "openshell_task_confirmed_not_occurred" {
			t.Fatalf("reason_code = %v", out["reason_code"])
		}
		recID := str(out["reconciliation_receipt_id"])
		if !strings.HasSuffix(recID, "-rec") || recID == reservationID {
			t.Fatalf("reconciliation_receipt_id = %q, want the signed closure receipt", recID)
		}
		if !strings.Contains(str(out["note"]), "不重放") {
			t.Fatalf("reconciliation note must state that nothing is replayed: %q", out["note"])
		}

		// The closure is a signed projection input, so a later status read
		// reports the same terminal state without touching the task.
		if code, doc := taskTrackStatus(t, s, token, taskTrackStatusBody(reservationID, decision)); code != 200 || doc["state"] != "reconciled_not_occurred" {
			t.Fatalf("status after reconciliation: HTTP %d %v", code, doc)
		}

		// Closing is idempotent in the recorded outcome only.
		again := taskTrackReconcileBody(t, s, reservationID, decision, receipt.HoldExecutionNotOccurred)
		if code, out := taskTrackReconcile(t, s, s.bootAdmin, again); code != 200 || out["state"] != "reconciled_not_occurred" {
			t.Fatalf("repeat reconciliation: HTTP %d %v, want 200 (idempotent)", code, out)
		}
		// A different outcome after the fact is a conflict, never a rewrite.
		flip := taskTrackReconcileBody(t, s, reservationID, decision, receipt.HoldExecutionOccurred)
		code, out = taskTrackReconcile(t, s, s.bootAdmin, flip)
		if code != 409 || str(out["error"]) != "openshell_task_reconcile_conflict" {
			t.Fatalf("opposite outcome: HTTP %d %v, want 409 conflict", code, out)
		}

		// The reconciliation is a projection input, not a re-execution.
		if spy.callCount() != 1 {
			t.Fatalf("reconciliation re-ran the task: %d runner calls", spy.callCount())
		}
	})
}

// TestOpenShellTaskReconcileRejectsPolicyApplyReservations proves the
// task-execution contract cannot be used to close a reservation that belongs to
// the policy-apply route, even with a valid admin credential and the exact
// signed identity. Policy side effects and task side effects stay separate.
func TestOpenShellTaskReconcileRejectsPolicyApplyReservations(t *testing.T) {
	s, _ := newSessionExecServer(t)

	decision := sessionExecApproveHold(t, s)
	res := sessionExecPostOK(t, s, "/v1/openshell/session-executions", token, sessionExecBody(decision))
	reservation := mustKey(t, res, "reservation")
	reservationID := str(reservation["reservation_receipt_id"])
	if reservationID == "" {
		t.Fatalf("policy-apply reservation id missing: %v", res)
	}
	hash := s.chainReceiptHash(reservationID)
	if !taskHex64(hash) {
		t.Fatalf("policy-apply reservation has no verifiable chain hash")
	}

	code, out := taskTrackReconcile(t, s, s.bootAdmin, map[string]any{
		"schema_version":         openshellTaskReconcileSchema,
		"reservation_receipt_id": reservationID,
		"reservation_hash":       hash,
		"action_id":              decision["action_id"],
		"decision_receipt_id":    decision["receipt_id"],
		"outcome":                receipt.HoldExecutionNotOccurred,
		"actor_id":               "fixture-admin",
		"evidence_note":          "policy apply is not a task execution",
	})
	if code != 404 || str(out["error"]) != "openshell_task_reservation_unknown" {
		t.Fatalf("HTTP %d %v, want 404 openshell_task_reservation_unknown", code, out)
	}
	if matches, err := filepath.Glob(filepath.Join(s.d.Store.Dir, "evidence", "ostart-*.json")); err != nil || len(matches) != 0 {
		t.Fatalf("policy-apply reservation created task launch evidence: %v (%v)", matches, err)
	}
}

// TestOpenShellTaskReadServesTheSameProjectionToAnAdminSession proves the
// management console can see the state of a task it approved, and that the
// route which makes that possible is a READ.
//
// The console holds an administrator session and never a decision credential,
// so /status is closed to it. Rather than widen /status to two credentials,
// /read registers the SAME handler behind the administrator gate. These cases
// hold that to account: the two routes must return identical documents (or they
// would drift into two disagreeing accounts of one execution), every other
// credential must be refused, and reading must leave no trace in durable state.
func TestOpenShellTaskReadServesTheSameProjectionToAnAdminSession(t *testing.T) {
	spy := &taskSpy{}
	s, decision, reservationID := taskTrackRun(t, spy)
	body := taskTrackStatusBody(reservationID, decision)

	t.Run("only an administrator session is accepted", func(t *testing.T) {
		for _, c := range []struct {
			name  string
			token string
			want  int
		}{
			{"admin", s.bootAdmin, 200},
			{"decision credential", token, 403},
			{"none", "", 401},
			{"unknown", "not-a-credential", 401},
		} {
			if code, out := taskTrackRead(t, s, c.token, body); code != c.want {
				t.Fatalf("%s on /read: HTTP %d %v, want %d", c.name, code, out, c.want)
			}
		}
		// The decision-gated route must stay decision-gated: adding an
		// administrator read path must not have opened /status to sessions.
		if code, out := taskTrackStatus(t, s, s.bootAdmin, body); code != 401 {
			t.Fatalf("an administrator session reached /status: HTTP %d %v", code, out)
		}
	})

	chainBefore := taskTrackChainLen(t, s)
	_, viaStatus := taskTrackStatus(t, s, token, body)
	_, viaRead := taskTrackRead(t, s, s.bootAdmin, body)

	t.Run("the two routes cannot disagree", func(t *testing.T) {
		if !reflect.DeepEqual(viaStatus, viaRead) {
			t.Fatalf("admin view differs from decision view:\nstatus=%v\nread=%v", viaStatus, viaRead)
		}
		if viaRead["state"] != openshell.TaskStateSucceeded {
			t.Fatalf("state = %v, want %v", viaRead["state"], openshell.TaskStateSucceeded)
		}
	})

	t.Run("reading is not a side effect", func(t *testing.T) {
		if spy.callCount() != 1 {
			t.Fatalf("runner calls = %d, want 1: a read must not execute", spy.callCount())
		}
		if after := taskTrackChainLen(t, s); after != chainBefore {
			t.Fatalf("chain grew from %d to %d: a read wrote state", chainBefore, after)
		}
		if _, err := os.Stat(taskTrackEvidencePath(s, openshellTaskStopEvidenceID(reservationID))); !os.IsNotExist(err) {
			t.Fatalf("a read created a stop record: %v", err)
		}
	})

	t.Run("read cannot stop or reconcile", func(t *testing.T) {
		// Both bodies are valid for their OWN route and name the same real
		// reservation. Presented to /read they are refused before any handler
		// branch can run: the read route decodes strictly, and every acting
		// field (stop's "target"/"actor_id", reconcile's "outcome"/
		// "reservation_hash") is unknown to the status request, so the decoder
		// rejects the body outright. 400 rather than 200 is the assertion that
		// matters — /read has no branch that acts on either intent.
		for name, foreignBody := range map[string]any{
			"stop body":      taskTrackStopBody(reservationID, decision),
			"reconcile body": taskTrackReconcileBody(t, s, reservationID, decision, receipt.HoldExecutionNotOccurred),
		} {
			code, out := taskTrackRead(t, s, s.bootAdmin, foreignBody)
			if code != 400 {
				t.Fatalf("%s on /read: HTTP %d %v, want 400 refusal", name, code, out)
			}
			switch str(out["error"]) {
			case "invalid json", "invalid_openshell_task_status_shape":
			default:
				t.Fatalf("%s on /read: refused as %q, want a decode or shape refusal", name, str(out["error"]))
			}
		}
		if after := taskTrackChainLen(t, s); after != chainBefore {
			t.Fatalf("chain grew from %d to %d: a read acted", chainBefore, after)
		}
		if _, err := os.Stat(taskTrackEvidencePath(s, openshellTaskStopEvidenceID(reservationID))); !os.IsNotExist(err) {
			t.Fatalf("a read recorded a stop: %v", err)
		}
	})

	t.Run("administrator read hides nothing from its own operator and grants nothing", func(t *testing.T) {
		// The projection stays redacted for the administrator exactly as it is for
		// the decision credential: the wider credential buys reach, not detail.
		output := mustKey(t, viaRead, "output")
		if output["raw_stored"] != false || output["raw_opt_in"] != false {
			t.Fatalf("admin view unredacted the output: %v", output)
		}
		encoded, err := json.Marshal(viaRead)
		if err != nil {
			t.Fatal(err)
		}
		for _, arg := range taskExecArgv {
			if strings.Contains(string(encoded), arg) {
				t.Fatalf("admin view leaked raw argv %q: %s", arg, encoded)
			}
		}
	})

	t.Run("unknown reservation is not an existence oracle", func(t *testing.T) {
		// Same non-disclosing answer as /status: a named-but-unknown reservation
		// and a reservation that exists but belongs to someone else are
		// indistinguishable.
		code, out := taskTrackRead(t, s, s.bootAdmin, taskTrackStatusBody("rcp-does-not-exist", decision))
		if code != 404 || str(out["error"]) != "openshell_task_reservation_unknown" {
			t.Fatalf("unknown reservation: HTTP %d %v, want 404", code, out)
		}
		foreign := taskTrackStatusBody(reservationID, decision)
		foreign["agent_id"] = "inst_other"
		code, out = taskTrackRead(t, s, s.bootAdmin, foreign)
		if code != 404 || str(out["error"]) != "openshell_task_reservation_mismatch" {
			t.Fatalf("foreign identity: HTTP %d %v, want 404", code, out)
		}
	})
}

// TestOpenShellTaskReadTellsTheOperatorAFailure is the case the administrator
// route exists for: a task that did not succeed must be readable, and readable
// as unresolved rather than as a success, by the session that approved it.
func TestOpenShellTaskReadTellsTheOperatorAFailure(t *testing.T) {
	spy := &taskSpy{next: func(int) openshell.TaskRunResult {
		return openshell.TaskRunResult{ExitCode: 3, Stdout: "boom\n", Spawned: true}
	}}
	s, decision, reservationID := taskTrackReserve(t, spy)
	code, execOut := taskExecPost(t, s, token, taskExecBody(decision))
	if code != 502 || str(execOut["error"]) != "task_failed" {
		t.Fatalf("fixture execution: HTTP %d %v, want 502 task_failed", code, execOut)
	}

	readCode, doc := taskTrackRead(t, s, s.bootAdmin, taskTrackStatusBody(reservationID, decision))
	if readCode != 200 {
		t.Fatalf("administrator read of a failed task: HTTP %d %v", readCode, doc)
	}
	if doc["state"] == openshell.TaskStateSucceeded {
		t.Fatalf("a failed task read as succeeded: %v", doc)
	}
	if _, present := doc["task_executed"]; present {
		t.Fatalf("the view invented an executed flag: %v", doc)
	}
	// The failure must be actionable without inviting a replay.
	if str(doc["reason_code"]) == "" || str(doc["note"]) == "" {
		t.Fatalf("an unresolved task must explain itself: %v", doc)
	}

	_, viaStatus := taskTrackStatus(t, s, token, taskTrackStatusBody(reservationID, decision))
	if !reflect.DeepEqual(doc, viaStatus) {
		t.Fatalf("admin and decision views disagree on a failure:\nread=%v\nstatus=%v", doc, viaStatus)
	}
}

func blockTaskAudit(t *testing.T, s *Server) {
	t.Helper()
	path := filepath.Join(s.d.Store.Dir, "audit.jsonl")
	if err := os.Rename(path, path+".preserved"); err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	if err := os.Mkdir(path, 0700); err != nil {
		t.Fatal(err)
	}
}

func TestOpenShellTaskStopAuditFailureDoesNotCancel(t *testing.T) {
	started, release, done := make(chan struct{}), make(chan struct{}), make(chan struct{})
	canceled := make(chan struct{}, 1)
	contexts := make(chan context.Context, 1)
	s := newTaskRunnerServer(t, func(ctx context.Context, args []string, timeout time.Duration, limit int) openshell.TaskRunResult {
		contexts <- ctx
		close(started)
		select {
		case <-ctx.Done():
			canceled <- struct{}{}
		case <-release:
		}
		return openshell.TaskRunResult{ExitCode: 1, Spawned: true}
	})
	decision := taskExecApproveHold(t, s)
	go func() { defer close(done); _, _ = taskExecPost(t, s, token, taskExecBody(decision)) }()
	defer func() { close(release); <-done }()
	select {
	case <-started:
	case <-time.After(10 * time.Second):
		t.Fatal("not started")
	}
	runContext := <-contexts
	blockTaskAudit(t, s)
	reservationID := str(decision["receipt_id"]) + "-exec"
	code, out := taskTrackStop(t, s, token, taskTrackStopBody(reservationID, decision))
	if code != 503 || out["error"] != "stop_audit_not_persisted" {
		t.Fatalf("HTTP %d %v", code, out)
	}
	if runContext.Err() != nil {
		t.Fatal("audit failure canceled the context")
	}
	select {
	case <-canceled:
		t.Fatal("unaudited stop canceled task")
	default:
	}
	ev, err := s.d.Store.GetEvidence(openshellTaskStopEvidenceID(reservationID))
	if err != nil || ev != nil {
		t.Fatalf("stop intent persisted despite audit failure: %v %v", ev, err)
	}
}

func TestOpenShellTaskReconcileAuditFailureDoesNotClose(t *testing.T) {
	spy := &taskSpy{next: func(int) openshell.TaskRunResult { return openshell.TaskRunResult{ExitCode: 3, Spawned: true} }}
	s, decision, id := taskTrackReserve(t, spy)
	code, _ := taskExecPost(t, s, token, taskExecBody(decision))
	if code != 502 {
		t.Fatal(code)
	}
	body := taskTrackReconcileBody(t, s, id, decision, receipt.HoldExecutionNotOccurred)
	before := taskTrackChainLen(t, s)
	blockTaskAudit(t, s)
	code, out := taskTrackReconcile(t, s, s.bootAdmin, body)
	if code != 503 || out["reconciled"] != false || taskTrackChainLen(t, s) != before {
		t.Fatalf("unaudited reconciliation changed signed chain: HTTP %d %v", code, out)
	}
}
