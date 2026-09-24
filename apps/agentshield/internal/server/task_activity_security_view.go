package server

import (
	"fmt"
	"net/http"
	"sort"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/completion"
	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

const (
	taskSecurityReceiptLimit     = 10000
	taskSecurityDestinationLimit = 1024
	taskSecurityModelLimit       = 64
)

type taskSecurityBusinessObject struct {
	Status       string  `json:"status"`
	ObjectType   string  `json:"object_type"`
	TaskID       *string `json:"task_id"`
	IntentID     *string `json:"intent_id"`
	Contract     string  `json:"contract_status"`
	DisplayLabel string  `json:"display_label_status"`
}

type taskSecurityRunMode struct {
	Platform          *string  `json:"platform"`
	EnforcementModes  []string `json:"enforcement_modes"`
	ModeStatus        string   `json:"mode_status"`
	ModelKeys         []string `json:"model_keys"`
	ModelStatus       string   `json:"model_status"`
	ExecutionContext  string   `json:"execution_context"`
	SandboxBoundCount int      `json:"sandbox_bound_receipts"`
}

type taskSecurityDestination struct {
	Domain       string   `json:"domain"`
	ResourceRef  string   `json:"resource_ref"`
	Effects      []string `json:"effects"`
	ReceiptCount int      `json:"receipt_count"`
}

type taskSecurityDataDestinations struct {
	Status                 string                    `json:"status"`
	Destinations           []taskSecurityDestination `json:"destinations"`
	UnresolvedReceiptCount int                       `json:"unresolved_receipt_count"`
	PlaintextExposed       bool                      `json:"plaintext_exposed"`
}

type taskSecurityDecisionCounts struct {
	Authorized int `json:"authorized"`
	Denied     int `json:"denied"`
	Pending    int `json:"pending"`
	Unknown    int `json:"unknown"`
}

type taskSecurityAuthorization struct {
	Status            string                     `json:"status"`
	IntentBinding     string                     `json:"intent_binding"`
	Decisions         taskSecurityDecisionCounts `json:"decisions"`
	MatchedGrantCount int                        `json:"matched_grant_count"`
}

type taskSecurityActualResult struct {
	Status           string             `json:"status"`
	EvaluationStatus string             `json:"evaluation_status"`
	ReasonCode       string             `json:"reason_code"`
	Result           *completion.Result `json:"result"`
}

type taskSecurityReleaseAssurance struct {
	Status     string `json:"status"`
	ReasonCode string `json:"reason_code"`
}

type taskSecurityIntegrity struct {
	PrefixValid bool   `json:"prefix_valid"`
	History     string `json:"history_integrity"`
	Freshness   string `json:"evidence_freshness"`
}

type taskSecurityView struct {
	Schema            string                       `json:"schema_version"`
	Snapshot          string                       `json:"snapshot"`
	EvaluatedAt       string                       `json:"evaluated_at"`
	Activity          taskActivityItem             `json:"activity"`
	BusinessObject    taskSecurityBusinessObject   `json:"business_object"`
	RunMode           taskSecurityRunMode          `json:"run_mode"`
	DataDestinations  taskSecurityDataDestinations `json:"data_destinations"`
	Authorization     taskSecurityAuthorization    `json:"authorization"`
	ActualResult      taskSecurityActualResult     `json:"actual_result"`
	ReleaseAssurance  taskSecurityReleaseAssurance `json:"release_assurance"`
	EvidenceIntegrity taskSecurityIntegrity        `json:"evidence_integrity"`
}

type projectedDecision struct {
	action, authority, binding string
}

func taskSecurityBusiness(activity taskActivityItem, completionReason string) taskSecurityBusinessObject {
	out := taskSecurityBusinessObject{Status: "unknown", ObjectType: "task", Contract: "unattributed", DisplayLabel: "unavailable"}
	if activity.Binding == nil {
		return out
	}
	taskID, intentID := activity.Binding["task_id"], activity.Binding["intent_id"]
	out.Status, out.TaskID, out.IntentID = "referenced", &taskID, &intentID
	switch completionReason {
	case "evaluated":
		out.Status, out.Contract = "verified", "verified"
	case "intent_missing":
		out.Contract = "missing"
	default:
		out.Contract = "unknown"
	}
	return out
}

func safeSecurityLabel(value string) bool {
	if len(value) == 0 || len(value) > 256 || !utf8.ValidString(value) {
		return false
	}
	for _, r := range value {
		if unicode.IsControl(r) {
			return false
		}
	}
	return true
}

func taskSecurityMode(activity taskActivityItem, receipts []receipt.Receipt) (taskSecurityRunMode, bool) {
	out := taskSecurityRunMode{EnforcementModes: []string{}, ModeStatus: "unknown", ModelKeys: []string{}, ModelStatus: "unknown", ExecutionContext: "unrecorded"}
	if activity.Binding != nil {
		platform := activity.Binding["platform"]
		out.Platform = &platform
	} else if len(receipts) > 0 && receipts[0].Platform != "" {
		platform := receipts[0].Platform
		out.Platform = &platform
	}
	modes := map[string]bool{}
	models := map[string]bool{}
	unknownMode, unknownModel, missingSandbox := 0, 0, 0
	for _, rc := range receipts {
		switch rc.EnforcementMode {
		case "block", "warn", "audit_only":
			modes[rc.EnforcementMode] = true
		default:
			unknownMode++
		}
		if rc.ModelKey == nil || !safeSecurityLabel(*rc.ModelKey) {
			unknownModel++
		} else {
			models[*rc.ModelKey] = true
			if len(models) > taskSecurityModelLimit {
				return out, false
			}
		}
		if rc.SandboxID == nil || *rc.SandboxID == "" {
			missingSandbox++
		} else {
			out.SandboxBoundCount++
		}
	}
	for mode := range modes {
		out.EnforcementModes = append(out.EnforcementModes, mode)
	}
	sort.Strings(out.EnforcementModes)
	for model := range models {
		out.ModelKeys = append(out.ModelKeys, model)
	}
	sort.Strings(out.ModelKeys)
	switch {
	case len(out.EnforcementModes) == 0:
		out.ModeStatus = "unknown"
	case len(out.EnforcementModes) == 1 && unknownMode == 0:
		out.ModeStatus = "consistent"
	default:
		out.ModeStatus = "mixed"
	}
	switch {
	case len(out.ModelKeys) == 0:
		out.ModelStatus = "unknown"
	case len(out.ModelKeys) == 1 && unknownModel == 0:
		out.ModelStatus = "consistent"
	default:
		out.ModelStatus = "mixed"
	}
	switch {
	case out.SandboxBoundCount == 0:
		out.ExecutionContext = "unrecorded"
	case missingSandbox == 0:
		out.ExecutionContext = "sandbox_bound"
	default:
		out.ExecutionContext = "mixed"
	}
	return out, true
}

func destinationEffect(effect string) bool {
	return strings.HasPrefix(effect, "file.") || effect == "network.request" || effect == "message.send" || strings.HasPrefix(effect, "database.") || effect == "secret.read"
}

func taskSecurityDestinations(receipts []receipt.Receipt) (taskSecurityDataDestinations, bool) {
	type entry struct {
		domain, digest string
		effects        map[string]bool
		count          int
	}
	out := taskSecurityDataDestinations{Status: "unknown", Destinations: []taskSecurityDestination{}, PlaintextExposed: false}
	entries := map[string]*entry{}
	for _, rc := range receipts {
		requiresDestination := false
		for _, effect := range rc.Effects {
			if destinationEffect(effect) {
				requiresDestination = true
			}
		}
		validRefs := 0
		seenRefs := map[string]bool{}
		for _, ref := range rc.ResourceRefs {
			if (ref.Domain != "filesystem" && ref.Domain != "network" && ref.Domain != "message") || len(ref.Digest) != 64 || strings.Trim(ref.Digest, "0123456789abcdef") != "" {
				continue
			}
			key := ref.Domain + ":" + ref.Digest
			if seenRefs[key] {
				continue
			}
			seenRefs[key] = true
			item := entries[key]
			if item == nil {
				if len(entries) >= taskSecurityDestinationLimit {
					return out, false
				}
				item = &entry{domain: ref.Domain, digest: ref.Digest, effects: map[string]bool{}}
				entries[key] = item
			}
			item.count++
			for _, effect := range rc.Effects {
				item.effects[effect] = true
			}
			validRefs++
		}
		if requiresDestination && validRefs == 0 {
			out.UnresolvedReceiptCount++
		}
	}
	keys := make([]string, 0, len(entries))
	for key := range entries {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		item := entries[key]
		effects := make([]string, 0, len(item.effects))
		for effect := range item.effects {
			effects = append(effects, effect)
		}
		sort.Strings(effects)
		out.Destinations = append(out.Destinations, taskSecurityDestination{Domain: item.domain, ResourceRef: item.digest, Effects: effects, ReceiptCount: item.count})
	}
	switch {
	case len(out.Destinations) == 0:
		out.Status = "unknown"
	case out.UnresolvedReceiptCount > 0:
		out.Status = "partial"
	default:
		out.Status = "observed"
	}
	return out, true
}

func taskSecurityAuthorizationSummary(activity taskActivityItem, receipts []receipt.Receipt) taskSecurityAuthorization {
	out := taskSecurityAuthorization{Status: "unknown", IntentBinding: "unknown"}
	if activity.Binding != nil {
		out.IntentBinding = "bound"
	}
	decisions := map[string]projectedDecision{}
	grants := map[string]bool{}
	for _, rc := range receipts {
		action := rc.EffectiveAction
		if action == "" {
			action = rc.Action
		}
		key := rc.ActionID
		if key == "" {
			key = fmt.Sprintf("seq:%d", rc.Seq)
		}
		grant := ""
		if rc.MatchedGrantID != nil {
			grant = *rc.MatchedGrantID
			if grant != "" {
				grants[grant] = true
			}
		}
		decisions[key] = projectedDecision{action: action, authority: rc.AuthorityStatus, binding: rc.IntentBinding}
	}
	for _, decision := range decisions {
		switch decision.action {
		case receipt.ActionDeny:
			out.Decisions.Denied++
		case receipt.ActionHold:
			out.Decisions.Pending++
		case receipt.ActionAllow, receipt.ActionRedact:
			if decision.authority == "valid" && decision.binding == "bound" {
				out.Decisions.Authorized++
			} else {
				out.Decisions.Unknown++
			}
		default:
			out.Decisions.Unknown++
		}
	}
	out.MatchedGrantCount = len(grants)
	nonzero := 0
	for _, count := range []int{out.Decisions.Authorized, out.Decisions.Denied, out.Decisions.Pending, out.Decisions.Unknown} {
		if count > 0 {
			nonzero++
		}
	}
	switch {
	case nonzero != 1:
		if nonzero > 1 {
			out.Status = "mixed"
		}
	case out.Decisions.Authorized > 0:
		out.Status = "authorized"
	case out.Decisions.Denied > 0:
		out.Status = "denied"
	case out.Decisions.Pending > 0:
		out.Status = "pending"
	}
	return out
}

func taskSecurityResult(reason string, result *completion.Result) taskSecurityActualResult {
	out := taskSecurityActualResult{Status: "unknown", EvaluationStatus: reason, ReasonCode: reason, Result: result}
	if result != nil {
		out.Status, out.ReasonCode = result.Status, result.ReasonCode
	}
	return out
}

func (s *Server) taskActivitySecurityView(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/v1/task-activities/"), "/security-view")
	if len(id) != 64 || strings.Trim(id, "0123456789abcdef") != "" {
		w.WriteHeader(http.StatusNotFound)
		return
	}
	q, invalid := parseActivityQuery(r)
	if invalid || q.snapshot == "" || r.URL.Query().Has("offset") || r.URL.Query().Has("limit") {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "task_activity_query_invalid"})
		return
	}
	all, projection, err := s.d.Engine.TaskActivitySnapshot()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "task_activity_snapshot_unavailable"})
		return
	}
	meta := projectActivityPage(all, projection, q.view, 0, 0)
	if q.snapshot != meta.Snapshot {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "task_activity_snapshot_changed"})
		return
	}
	activity, indexes, found := findTaskActivity(all, projection, q.view, id)
	if !found {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "task_activity_not_found"})
		return
	}
	if len(indexes) > taskSecurityReceiptLimit {
		writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"error": "task_activity_security_view_limit"})
		return
	}
	receipts := make([]receipt.Receipt, 0, len(indexes))
	for _, index := range indexes {
		receipts = append(receipts, all[index])
	}
	destinations, ok := taskSecurityDestinations(receipts)
	if !ok {
		writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"error": "task_activity_security_destinations_limit"})
		return
	}
	runMode, ok := taskSecurityMode(activity, receipts)
	if !ok {
		writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"error": "task_activity_security_models_limit"})
		return
	}
	now := time.Now()
	reason, result, effects, failure := "attribution_unknown", (*completion.Result)(nil), []effectevidence.Record{}, ""
	if activity.Binding != nil {
		reason, result, effects, failure = s.evaluateActivityCompletion(activity, now)
		if failure != "" {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": failure})
			return
		}
	}
	out := taskSecurityView{
		Schema: "local-task-security-view/v1", Snapshot: meta.Snapshot, EvaluatedAt: now.UTC().Format(time.RFC3339Nano), Activity: activity,
		BusinessObject: taskSecurityBusiness(activity, reason), RunMode: runMode, DataDestinations: destinations,
		Authorization: taskSecurityAuthorizationSummary(activity, receipts), ActualResult: taskSecurityResult(reason, result),
		ReleaseAssurance:  taskSecurityReleaseAssurance{Status: "not_evaluated", ReasonCode: "native_candidate_evidence_not_connected"},
		EvidenceIntegrity: taskSecurityIntegrity{PrefixValid: meta.PrefixValid, History: meta.History, Freshness: meta.Freshness},
	}
	latest, latestProjection, err := s.d.Engine.TaskActivitySnapshot()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "task_activity_snapshot_unavailable"})
		return
	}
	latestEffects := effects
	if result != nil {
		latestEffects, err = s.effects.ForTask(activity.Binding["task_id"], now)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "completion_evidence_unavailable"})
			return
		}
	}
	if projectActivityPage(latest, latestProjection, q.view, 0, 0).Snapshot != meta.Snapshot || !sameTraceEffects(effects, latestEffects) {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "task_activity_snapshot_changed"})
		return
	}
	writeJSON(w, http.StatusOK, out)
}
