package server

import (
	"net/http"
	"strings"

	"siq-agent-security/apps/agentshield/internal/receipt"
)

type activityReceipt struct {
	ID         string  `json:"receipt_id"`
	Seq        int     `json:"seq"`
	Hash       string  `json:"hash"`
	IssuedAt   string  `json:"issued_at"`
	Platform   string  `json:"platform"`
	Session    string  `json:"session_id"`
	Agent      *string `json:"agent_id"`
	Action     string  `json:"action"`
	Reason     string  `json:"reason"`
	Tool       string  `json:"tool"`
	RecordType string  `json:"record_type"`
	ActionID   string  `json:"action_id"`
	DecisionID string  `json:"decision_receipt_id"`
	Grant      *string `json:"matched_grant_id"`
}

type taskActivityDetail struct {
	Schema      string            `json:"schema_version"`
	Snapshot    string            `json:"snapshot"`
	View        string            `json:"view"`
	Offset      int               `json:"offset"`
	Total       int               `json:"total"`
	Next        *int              `json:"next_offset"`
	PrefixValid bool              `json:"prefix_valid"`
	History     string            `json:"history_integrity"`
	Freshness   string            `json:"evidence_freshness"`
	Activity    taskActivityItem  `json:"activity"`
	Receipts    []activityReceipt `json:"receipts"`
}

func (s *Server) taskActivityDetail(w http.ResponseWriter, r *http.Request) {
	if strings.HasSuffix(r.URL.Path, "/outputs") || strings.HasSuffix(r.URL.Path, "/outputs/read") {
		s.taskActivityOutputs(w, r)
		return
	}
	if strings.HasSuffix(r.URL.Path, "/security-view") {
		s.taskActivitySecurityView(w, r)
		return
	}
	if strings.HasSuffix(r.URL.Path, "/trace-export") {
		s.taskActivityTraceExport(w, r)
		return
	}
	if strings.HasSuffix(r.URL.Path, "/sources") {
		s.taskActivitySources(w, r)
		return
	}
	if strings.HasSuffix(r.URL.Path, "/export") {
		s.taskActivityExport(w, r)
		return
	}
	if strings.HasSuffix(r.URL.Path, "/completion") {
		s.taskActivityCompletion(w, r)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/v1/task-activities/")
	if len(id) != 64 || strings.Trim(id, "0123456789abcdef") != "" {
		w.WriteHeader(404)
		return
	}
	q, invalid := parseActivityQuery(r)
	if invalid {
		writeJSON(w, 400, map[string]string{"error": "task_activity_query_invalid"})
		return
	}
	all, projection, err := s.d.Engine.TaskActivitySnapshot()
	if err != nil {
		writeJSON(w, 500, map[string]string{"error": "task_activity_snapshot_unavailable"})
		return
	}
	meta := projectActivityPage(all, projection, q.view, 0, 0)
	if q.snapshot != "" && q.snapshot != meta.Snapshot {
		writeJSON(w, 409, map[string]string{"error": "task_activity_snapshot_changed"})
		return
	}
	item, indexes, found := findTaskActivity(all, projection, q.view, id)
	if !found {
		writeJSON(w, 404, map[string]string{"error": "task_activity_not_found"})
		return
	}
	detail := taskActivityDetail{Schema: "local-task-activity-detail/v1", Snapshot: meta.Snapshot, View: q.view, Offset: q.offset, Total: len(indexes), PrefixValid: meta.PrefixValid, History: meta.History, Freshness: meta.Freshness, Activity: item, Receipts: []activityReceipt{}}
	end := q.offset + q.limit
	if end > len(indexes) {
		end = len(indexes)
	}
	for _, index := range indexes[min(q.offset, len(indexes)):end] {
		rc := all[index]
		detail.Receipts = append(detail.Receipts, activityReceipt{ID: rc.ReceiptID, Seq: rc.Seq, Hash: rc.Hash, IssuedAt: rc.IssuedAt, Platform: rc.Platform, Session: rc.SessionID, Agent: rc.AgentID, Action: rc.Action, Reason: rc.Reason, Tool: rc.Tool, RecordType: rc.RecordType, ActionID: rc.ActionID, DecisionID: rc.DecisionReceiptID, Grant: rc.MatchedGrantID})
	}
	if end < len(indexes) {
		detail.Next = &end
	}
	writeJSON(w, 200, detail)
}

func findTaskActivity(all []receipt.Receipt, projection receipt.TaskActivities, view, id string) (taskActivityItem, []int, bool) {
	if view == "unassigned" {
		for i, index := range projection.Unassigned {
			rc := all[index]
			if activityDigest([]any{rc.ChainID, rc.Seq, rc.Hash}) == id {
				return projectActivityPage(all, projection, view, i, 1).Items[0], []int{index}, true
			}
		}
	} else {
		for i, task := range projection.Tasks {
			if activityDigest(activityBinding(task.Key)) == id {
				return projectActivityPage(all, projection, view, i, 1).Items[0], task.ReceiptIndexes, true
			}
		}
	}
	return taskActivityItem{}, nil, false
}
