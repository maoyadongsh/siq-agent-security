package server

import (
	"net/http"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/completion"
	"siq-agent-security/apps/agentshield/internal/intent"
)

func (s *Server) taskCompletion(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" {
		w.WriteHeader(405)
		return
	}
	path := strings.TrimPrefix(r.URL.Path, "/v1/tasks/")
	if !strings.HasSuffix(path, "/completion") {
		w.WriteHeader(404)
		return
	}
	id := strings.TrimSuffix(path, "/completion")
	if !fileObservationID.MatchString(id) {
		w.WriteHeader(404)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	contracts, err := s.intents.List()
	if err != nil {
		writeJSON(w, 500, map[string]string{"error": "completion_authority_unavailable"})
		return
	}
	var selected *intent.Contract
	for i := range contracts {
		if contracts[i].TaskID == id {
			if selected != nil {
				writeJSON(w, 409, map[string]string{"error": "completion_intent_ambiguous"})
				return
			}
			selected = &contracts[i]
		}
	}
	if selected == nil {
		writeJSON(w, 404, map[string]string{"error": "completion_task_not_found"})
		return
	}
	now := time.Now()
	records, err := s.effects.ForTask(id, now)
	if err != nil {
		writeJSON(w, 500, map[string]string{"error": "completion_evidence_unavailable"})
		return
	}
	task := completion.Task{ID: id, IntentID: selected.IntentID, IntentDigest: selected.Digest}
	if selected.EffectRequirements != nil {
		task.Requirements = *selected.EffectRequirements
	}
	out, err := completion.Evaluate(task, records, s.d.Key.Public(), s.d.Engine.EffectAction, now)
	if err != nil {
		writeJSON(w, 500, map[string]string{"error": "completion_evidence_invalid"})
		return
	}
	writeJSON(w, 200, out)
}
