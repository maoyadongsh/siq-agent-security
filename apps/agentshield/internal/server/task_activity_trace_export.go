package server

import (
	"errors"
	"net/http"
	"os"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/completion"
	"siq-agent-security/apps/agentshield/internal/effectevidence"
	exportpkg "siq-agent-security/apps/agentshield/internal/export"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

const taskTraceSourceLimit = 8

func (s *Server) traceSources(all []receipt.Receipt, indexes []int) ([]exportpkg.TraceSourceInput, string) {
	out := make([]exportpkg.TraceSourceInput, 0, len(indexes))
	cache := map[intent.HistoricalGrantSubject]*intent.HistoricalSkillSource{}
	for _, index := range indexes {
		rc := all[index]
		row := exportpkg.TraceSourceInput{Seq: rc.Seq, ReceiptHash: rc.Hash, Status: "unavailable"}
		// The v1 trace source describes a single Intent-bound Grant. Native
		// authority is baseline plus a Skill ancestry, including explicit no-Skill.
		// Do not label baseline admission metadata as the invoked Skill source.
		if rc.SchemaVersion == "runtime-receipt/v3" || rc.NativeInvocation != nil {
			out = append(out, row)
			continue
		}
		if rc.MatchedGrantID != nil && *rc.MatchedGrantID != "" && rc.AgentID != nil {
			subject := intent.HistoricalGrantSubject{
				Platform: rc.Platform, SessionID: rc.SessionID, AgentID: *rc.AgentID, TaskID: rc.TaskID,
				IntentID: rc.IntentID, IntentDigest: rc.IntentDigest, AuthorityRevision: rc.AuthorityRevision, MatchedGrantID: *rc.MatchedGrantID,
			}
			source, exists := cache[subject]
			if !exists {
				if len(cache) >= taskTraceSourceLimit {
					return nil, "task_activity_trace_sources_limit"
				}
				value, err := s.intents.HistoricalSkillSource(subject, s.d.Store.GetHistoricalAdmission)
				if err == nil {
					source = &value
				}
				cache[subject] = source
			}
			if source != nil {
				copy := *source
				row.Status, row.Source = "verified_source", &copy
			}
		}
		out = append(out, row)
	}
	return out, ""
}

func (s *Server) evaluateActivityCompletion(activity taskActivityItem, now time.Time) (string, *completion.Result, []effectevidence.Record, string) {
	b := activity.Binding
	contract, err := s.intents.Get(b["intent_id"])
	if errors.Is(err, os.ErrNotExist) {
		return "intent_missing", nil, nil, ""
	}
	if err != nil || contract.TaskID != b["task_id"] || contract.Agent.ID != b["agent_id"] || contract.Agent.Platform != b["platform"] || contract.Digest != b["intent_digest"] {
		return "", nil, nil, "completion_authority_invalid"
	}
	records, err := s.effects.ForTask(contract.TaskID, now)
	if err != nil {
		return "", nil, nil, "completion_evidence_unavailable"
	}
	lookup, err := s.d.Engine.HistoricalEffectActions(records)
	if err != nil {
		return "", nil, nil, "completion_action_history_invalid"
	}
	task := completion.Task{ID: contract.TaskID, IntentID: contract.IntentID, IntentDigest: contract.Digest}
	if contract.EffectRequirements != nil {
		task.Requirements = *contract.EffectRequirements
	}
	result, err := completion.EvaluateForSubject(task, completion.Subject{Platform: b["platform"], SessionID: b["session_id"], AgentID: b["agent_id"]}, records, s.d.Key.Public(), lookup, now)
	if err != nil {
		return "", nil, nil, "completion_evidence_invalid"
	}
	return "evaluated", &result, records, ""
}

func sameTraceEffects(left, right []effectevidence.Record) bool {
	if len(left) != len(right) {
		return false
	}
	for i := range left {
		if left[i].Evidence.EvidenceID != right[i].Evidence.EvidenceID || left[i].Signature != right[i].Signature {
			return false
		}
	}
	return true
}

func (s *Server) taskActivityTraceExport(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/v1/task-activities/"), "/trace-export")
	if len(id) != 64 || strings.Trim(id, "0123456789abcdef") != "" {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	q, invalid := parseActivityQuery(r)
	if invalid || q.snapshot == "" || q.view != "tasks" || r.URL.Query().Has("offset") || r.URL.Query().Has("limit") {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "task_activity_query_invalid"})
		return
	}
	all, projection, err := s.d.Engine.TaskActivitySnapshot()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "task_activity_snapshot_unavailable"})
		return
	}
	meta := projectActivityPage(all, projection, "tasks", 0, 0)
	if q.snapshot != meta.Snapshot {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "task_activity_snapshot_changed"})
		return
	}
	activity, indexes, found := findTaskActivity(all, projection, "tasks", id)
	if !found {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "task_activity_not_found"})
		return
	}
	if len(indexes) > 10000 {
		writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"error": "task_activity_trace_limit"})
		return
	}
	var key receipt.TaskActivityKey
	for _, group := range projection.Tasks {
		if activityDigest(activityBinding(group.Key)) == id {
			key = group.Key
			break
		}
	}
	projected, err := exportpkg.ProjectActivity(all, s.d.Key.Public(), nil, key, 10000)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "task_activity_trace_unavailable"})
		return
	}
	now := time.Now()
	last := all[len(all)-1]
	activityDoc := exportpkg.ActivityDocument{
		ActivityID: id, Snapshot: meta.Snapshot, GeneratedAt: now.UTC().Format(time.RFC3339Nano), SourceCount: len(all),
		SourceTipHash: last.Hash, SourceLastSeq: last.Seq, PrefixValid: projection.Verification.PrefixValid,
		History: projection.Verification.HistoryIntegrity, Receipts: []exportpkg.ActivityExportRow{},
	}
	for _, row := range projected.Rows {
		activityDoc.Receipts = append(activityDoc.Receipts, exportpkg.ActivityExportRow{Seq: row.Seq, IssuedAt: row.IssuedAt, ReceiptRef: row.ReceiptRef, ToolRef: row.ToolRef, Action: row.Action, SourceHash: row.SourceHash})
	}
	if err := exportpkg.SealActivity(s.d.Key, &activityDoc); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "task_activity_trace_unavailable"})
		return
	}
	sources, sourceError := s.traceSources(all, indexes)
	if sourceError != "" {
		writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"error": sourceError})
		return
	}
	reason, result, effects, completionError := s.evaluateActivityCompletion(activity, now)
	if completionError != "" {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": completionError})
		return
	}
	doc, err := exportpkg.BuildTrace(s.d.Key, exportpkg.TraceInput{Activity: activityDoc, Sources: sources, TaskID: key.TaskID, CompletionReason: reason, Completion: result, Effects: effects, Now: now})
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "task_activity_trace_unavailable"})
		return
	}
	latest, latestProjection, err := s.d.Engine.TaskActivitySnapshot()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "task_activity_snapshot_unavailable"})
		return
	}
	latestEffects := effects
	if result != nil {
		latestEffects, err = s.effects.ForTask(key.TaskID, now)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "completion_evidence_unavailable"})
			return
		}
	}
	if projectActivityPage(latest, latestProjection, "tasks", 0, 0).Snapshot != meta.Snapshot || !sameTraceEffects(effects, latestEffects) {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "task_activity_trace_changed"})
		return
	}
	w.Header().Set("Content-Disposition", `attachment; filename="siq-trace-`+id+`.json"`)
	writeJSON(w, http.StatusOK, doc)
}
