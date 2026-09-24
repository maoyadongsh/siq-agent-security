package server

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net/http"
	"os"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/rawcontent"
)

type taskOutputs struct {
	Schema     string                `json:"schema_version"`
	ActivityID string                `json:"activity_id"`
	Snapshot   string                `json:"snapshot"`
	Status     string                `json:"status"`
	TaskRef    *string               `json:"task_ref"`
	Items      []rawcontent.Metadata `json:"items"`
}

type taskOutputRead struct {
	Schema         string `json:"schema_version"`
	RecordID       string `json:"record_id"`
	ExpectedDigest string `json:"expected_plaintext_sha256"`
	Confirm        bool   `json:"confirm_display"`
}

func (s *Server) taskActivityOutputs(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	isRead := strings.HasSuffix(r.URL.Path, "/outputs/read")
	method, suffix := http.MethodGet, "/outputs"
	if isRead {
		method, suffix = http.MethodPost, "/outputs/read"
	}
	if r.Method != method {
		w.WriteHeader(405)
		return
	}
	id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/v1/task-activities/"), suffix)
	if len(id) != 64 || strings.Trim(id, "0123456789abcdef") != "" {
		w.WriteHeader(404)
		return
	}
	q, invalid := parseActivityQuery(r)
	if invalid || q.snapshot == "" || q.view != "tasks" || r.URL.Query().Has("offset") || r.URL.Query().Has("limit") {
		writeJSON(w, 400, map[string]string{"error": "task_activity_query_invalid"})
		return
	}
	var req taskOutputRead
	if isRead {
		if !readStrictFlatRequest(w, r, &req, "task_output_read_invalid", "schema_version", "record_id", "expected_plaintext_sha256", "confirm_display") {
			return
		}
		if req.Schema != "local-task-output-read/v1" || !req.Confirm || len(req.ExpectedDigest) != 64 || strings.Trim(req.ExpectedDigest, "0123456789abcdef") != "" || len(req.RecordID) != 36 || !strings.HasPrefix(req.RecordID, "raw-") || strings.Trim(strings.TrimPrefix(req.RecordID, "raw-"), "0123456789abcdef") != "" {
			writeJSON(w, 400, map[string]string{"error": "task_output_read_invalid"})
			return
		}
	}
	all, projection, err := s.d.Engine.TaskActivitySnapshot()
	if err != nil {
		writeJSON(w, 503, map[string]string{"error": "task_activity_snapshot_unavailable"})
		return
	}
	meta := projectActivityPage(all, projection, q.view, 0, 0)
	if q.snapshot != meta.Snapshot || !meta.PrefixValid || meta.History == "failed" {
		writeJSON(w, 409, map[string]string{"error": "task_activity_snapshot_changed"})
		return
	}
	activity, _, found := findTaskActivity(all, projection, q.view, id)
	if !found {
		writeJSON(w, 404, map[string]string{"error": "task_activity_not_found"})
		return
	}
	out := taskOutputs{Schema: "local-task-outputs/v1", ActivityID: id, Snapshot: meta.Snapshot, Status: "unattributed", Items: []rawcontent.Metadata{}}
	b := activity.Binding
	identity, binding := "", ""
	if b != nil {
		sum := sha256.Sum256([]byte(b["task_id"]))
		ref := "sha256:" + hex.EncodeToString(sum[:])
		out.TaskRef = &ref
		identity, binding, err = s.runtimeIdentities.HistoricalSource(b["platform"], b["session_id"], b["agent_id"], b["task_id"], b["intent_id"], b["intent_digest"])
	}
	if b == nil || err != nil || identity == "" {
		if isRead {
			writeJSON(w, 409, map[string]string{"error": "task_output_source_unavailable"})
		} else {
			writeJSON(w, 200, out)
		}
		return
	}
	s.rawMu.Lock()
	defer s.rawMu.Unlock()
	status := s.refreshRawContentLocked()
	if status == "disabled" && !isRead {
		out.Status = "disabled"
		writeJSON(w, 200, out)
		return
	}
	if status != "ready" {
		writeJSON(w, 503, map[string]string{"error": "raw_task_content_unavailable"})
		return
	}
	now := time.Now()
	out.Status = "ready"
	var content rawTaskContentRecordContent
	if isRead {
		fields, envelope, err := s.rawStore.ReadRuntimeOutput(b["task_id"], identity, b["session_id"], binding, req.RecordID, now)
		if err != nil {
			code := 503
			if errors.Is(err, os.ErrNotExist) || errors.Is(err, rawcontent.ErrDenied) {
				code = 404
			}
			if errors.Is(err, rawcontent.ErrExpired) {
				code = 410
			}
			writeJSON(w, code, map[string]string{"error": "task_output_unavailable"})
			return
		}
		if envelope.PlaintextHash != req.ExpectedDigest {
			writeJSON(w, 409, map[string]string{"error": "task_output_changed"})
			return
		}
		plain := make([]rawTaskContentPlainField, len(fields))
		for i, f := range fields {
			plain[i] = rawTaskContentPlainField{Path: f.Path, Value: f.Value}
		}
		content = rawTaskContentRecordContent{SchemaVersion: "local-raw-task-content-record-content/v1", ContainsPlaintext: true,
			Record: rawcontent.Metadata{SchemaVersion: "local-raw-task-content-record/v1", Status: "active", RecordID: envelope.RecordID, TaskRef: envelope.TaskRef, Kind: envelope.Kind, CreatedAt: envelope.CreatedAt, ExpiresAt: envelope.ExpiresAt, PlaintextHash: envelope.PlaintextHash, PlaintextSize: envelope.PlaintextSize, OmittedCount: envelope.OmittedCount}, Fields: plain}
	} else {
		out.Items, err = s.rawStore.ListRuntimeOutputs(b["task_id"], identity, b["session_id"], binding, now)
		if err != nil {
			writeJSON(w, 503, map[string]string{"error": "task_output_unavailable"})
			return
		}
	}
	latest, projected, err := s.d.Engine.TaskActivitySnapshot()
	if err != nil {
		writeJSON(w, 503, map[string]string{"error": "task_activity_snapshot_unavailable"})
		return
	}
	if projectActivityPage(latest, projected, q.view, 0, 0).Snapshot != meta.Snapshot {
		writeJSON(w, 409, map[string]string{"error": "task_activity_snapshot_changed"})
		return
	}
	if isRead {
		writeJSON(w, 200, map[string]any{"schema_version": "local-task-output-content/v1", "activity_id": id, "snapshot": meta.Snapshot, "content": content})
	} else {
		writeJSON(w, 200, out)
	}
}
