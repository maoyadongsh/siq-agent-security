package server

import (
	"errors"
	"net/http"
	"strings"

	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/runtimecheck"
)

type runtimeCheckActivity struct {
	Schema     string           `json:"schema_version"`
	CheckID    string           `json:"check_id"`
	InstanceID string           `json:"instance_id"`
	Snapshot   string           `json:"snapshot"`
	Prefix     bool             `json:"prefix_valid"`
	History    string           `json:"history_integrity"`
	Activity   taskActivityItem `json:"activity"`
}

// Resolve against the verified full snapshot, never a paginated receipt list
// or an inferred task name. Every recorded receipt must share one binding.
func resolveRuntimeCheckActivity(result runtimecheck.Result, all []receipt.Receipt, projection receipt.TaskActivities) (runtimeCheckActivity, error) {
	fail := errors.New("runtime_check_activity_binding_changed")
	if !projection.Verification.PrefixValid || projection.Verification.HistoryIntegrity == "failed" || len(result.ReceiptIDs) == 0 {
		return runtimeCheckActivity{}, fail
	}
	wanted := make(map[string]bool, len(result.ReceiptIDs))
	for _, id := range result.ReceiptIDs {
		if id == "" || wanted[id] {
			return runtimeCheckActivity{}, fail
		}
		wanted[id] = true
	}
	counts := make(map[string]int, len(wanted))
	for _, rc := range all {
		if wanted[rc.ReceiptID] {
			counts[rc.ReceiptID]++
		}
	}
	for id := range wanted {
		if counts[id] != 1 {
			return runtimeCheckActivity{}, fail
		}
	}
	for index, task := range projection.Tasks {
		matched := 0
		for _, i := range task.ReceiptIndexes {
			if wanted[all[i].ReceiptID] {
				matched++
			}
		}
		if matched != len(wanted) || task.Key.Platform != "hermes" {
			continue
		}
		page := projectActivityPage(all, projection, "tasks", index, 1)
		return runtimeCheckActivity{Schema: "local-runtime-check-activity/v1", CheckID: result.ID, InstanceID: result.InstanceID,
			Snapshot: page.Snapshot, Prefix: true, History: page.History, Activity: page.Items[0]}, nil
	}
	return runtimeCheckActivity{}, fail
}

func (s *Server) runtimeCheckActivity(w http.ResponseWriter, r *http.Request, id string) {
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	if r.URL.RawQuery != "" || r.URL.ForceQuery {
		runtimeCheckError(w, errors.New("runtime_check_invalid_request"))
		return
	}
	result, err := s.runtimeChecks.Get(id)
	if err != nil {
		runtimeCheckError(w, err)
		return
	}
	if result.Status == "preparing" || result.Status == "waiting_host" || result.Status == "running" {
		runtimeCheckError(w, errors.New("runtime_check_activity_not_ready"))
		return
	}
	if len(result.ReceiptIDs) == 0 {
		runtimeCheckError(w, runtimecheck.ErrNotFound)
		return
	}
	all, projection, err := s.d.Engine.TaskActivitySnapshot()
	if err != nil {
		runtimeCheckError(w, errors.New("runtime_check_activity_unavailable"))
		return
	}
	activity, err := resolveRuntimeCheckActivity(result, all, projection)
	if err != nil {
		runtimeCheckError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, activity)
}

func runtimeCheckActivityID(path string) string {
	return strings.TrimSuffix(strings.TrimPrefix(path, "/v1/runtime-checks/"), "/activity")
}
