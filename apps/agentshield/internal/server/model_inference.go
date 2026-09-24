package server

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"regexp"
	"time"

	"siq-agent-security/apps/agentshield/internal/modelconfig"
)

var inferenceRequestID = regexp.MustCompile(`^mt-[0-9a-f]{32}$`)
var inferenceModelID = regexp.MustCompile(`^mc-[0-9a-f]{32}$`)
var inferenceFingerprint = regexp.MustCompile(`^[0-9a-f]{64}$`)

type modelInferenceRecord struct {
	Schema       string `json:"schema_version"`
	RequestID    string `json:"request_id"`
	ModelID      string `json:"model_id"`
	Fingerprint  string `json:"fingerprint"`
	Status       string `json:"status"`
	StartedAt    string `json:"started_at"`
	FinishedAt   string `json:"finished_at"`
	ExpiresAt    string `json:"expires_at"`
	Inference    bool   `json:"inference_verified"`
	BusinessData bool   `json:"business_data_sent"`
	SessionOnly  bool   `json:"service_session_only"`
}

func (s *Server) findInferenceTarget(id, fp string) (modelconfig.Target, bool) {
	targets, _ := s.modelTargets()
	for _, t := range targets {
		if t.Item.ID == id && t.Item.Fingerprint == fp && t.Item.CanCheck {
			return t, true
		}
	}
	return modelconfig.Target{}, false
}
func (s *Server) modelInferenceTests(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method == http.MethodGet {
		q := r.URL.Query()
		if len(q) != 1 || len(q["model_id"]) != 1 || !inferenceModelID.MatchString(q.Get("model_id")) {
			writeJSON(w, 400, map[string]string{"error": "model_test_request_invalid"})
			return
		}
		s.modelTestMu.Lock()
		var record *modelInferenceRecord
		if id := s.modelTestLatest[q.Get("model_id")]; id != "" {
			copy := s.modelTests[id]
			record = &copy
		}
		s.modelTestMu.Unlock()
		writeJSON(w, 200, map[string]any{"schema_version": "local-model-inference-latest/v1", "record": record})
		return
	}
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var body struct {
		Schema      string `json:"schema_version"`
		RequestID   string `json:"request_id"`
		ModelID     string `json:"model_id"`
		Fingerprint string `json:"fingerprint"`
		Confirm     bool   `json:"confirm_test"`
	}
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 4096))
	if err != nil || r.URL.RawQuery != "" || !exactJSONObject(raw, "schema_version", "request_id", "model_id", "fingerprint", "confirm_test") || json.Unmarshal(raw, &body) != nil || body.Schema != "local-model-inference-create/v1" || !body.Confirm || !inferenceRequestID.MatchString(body.RequestID) || !inferenceModelID.MatchString(body.ModelID) || !inferenceFingerprint.MatchString(body.Fingerprint) {
		writeJSON(w, 400, map[string]string{"error": "model_test_request_invalid"})
		return
	}
	s.modelTestMu.Lock()
	if old, exists := s.modelTests[body.RequestID]; exists {
		s.modelTestMu.Unlock()
		if old.ModelID != body.ModelID || old.Fingerprint != body.Fingerprint {
			writeJSON(w, 409, map[string]string{"error": "model_test_request_changed"})
			return
		}
		writeJSON(w, 200, old)
		return
	}
	if s.modelTestRunning || len(s.modelTests) >= 1024 {
		s.modelTestMu.Unlock()
		writeJSON(w, 409, map[string]string{"error": "model_test_busy_or_limit"})
		return
	}
	if _, ok := s.findInferenceTarget(body.ModelID, body.Fingerprint); !ok {
		s.modelTestMu.Unlock()
		writeJSON(w, 409, map[string]string{"error": "model_configuration_changed"})
		return
	}
	if s.modelTests == nil {
		s.modelTests = map[string]modelInferenceRecord{}
		s.modelTestLatest = map[string]string{}
	}
	record := modelInferenceRecord{Schema: "local-model-inference-record/v1", RequestID: body.RequestID, ModelID: body.ModelID, Fingerprint: body.Fingerprint, Status: "running", StartedAt: time.Now().UTC().Format(time.RFC3339Nano), SessionOnly: true}
	s.modelTests[body.RequestID] = record
	s.modelTestLatest[body.ModelID] = body.RequestID
	s.modelTestRunning = true
	s.modelTestMu.Unlock()
	// Independent of the browser connection. No retries after an uncertain send.
	go func(record modelInferenceRecord) {
		status := "configuration_changed"
		if target, ok := s.findInferenceTarget(record.ModelID, record.Fingerprint); ok {
			status = modelconfig.Infer(context.Background(), target)
			if _, ok = s.findInferenceTarget(record.ModelID, record.Fingerprint); !ok {
				status = "configuration_changed"
			}
		}
		now := time.Now().UTC()
		s.modelTestMu.Lock()
		defer s.modelTestMu.Unlock()
		record.Status = status
		record.Inference = status == "passed"
		record.FinishedAt = now.Format(time.RFC3339Nano)
		record.ExpiresAt = now.Add(5 * time.Minute).Format(time.RFC3339Nano)
		s.modelTests[record.RequestID] = record
		s.modelTestRunning = false
	}(record)
	writeJSON(w, 202, record)
}
