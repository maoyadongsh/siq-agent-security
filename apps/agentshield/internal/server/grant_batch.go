package server

import (
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

type grantBatchTarget struct {
	GrantID          string `json:"grant_id"`
	ExpectedRevision *int   `json:"expected_revision"`
}

func (target *grantBatchTarget) UnmarshalJSON(raw []byte) error {
	if !exactJSONObject(raw, "grant_id", "expected_revision") {
		return errors.New("invalid batch target")
	}
	type plain grantBatchTarget
	return json.Unmarshal(raw, (*plain)(target))
}

type grantBatchItem struct {
	GrantID          string `json:"grant_id"`
	ExpectedRevision int    `json:"expected_revision"`
	SubjectID        string `json:"subject_id"`
	Platform         string `json:"platform"`
	Status           string `json:"status"`
}

func (item *grantBatchItem) UnmarshalJSON(raw []byte) error {
	if !exactJSONObject(raw, "grant_id", "expected_revision", "subject_id", "platform", "status") {
		return errors.New("invalid batch plan item")
	}
	type plain grantBatchItem
	return json.Unmarshal(raw, (*plain)(item))
}

type grantBatchPlan struct {
	SchemaVersion string           `json:"schema_version"`
	SigningSchema string           `json:"signing_schema"`
	Signature     string           `json:"signature"`
	BatchID       string           `json:"batch_id"`
	ActorID       string           `json:"actor_id"`
	Action        string           `json:"action"`
	ExpiresAt     string           `json:"expires_at"`
	Items         []grantBatchItem `json:"items"`
}

func (plan *grantBatchPlan) UnmarshalJSON(raw []byte) error {
	if !exactJSONObject(raw, "schema_version", "signing_schema", "signature", "batch_id", "actor_id", "action", "expires_at", "items") {
		return errors.New("invalid batch plan")
	}
	type plain grantBatchPlan
	return json.Unmarshal(raw, (*plain)(plan))
}

type grantBatchResultItem struct {
	GrantID       string `json:"grant_id"`
	Status        string `json:"status"`
	StateRevision *int   `json:"state_revision,omitempty"`
}

func (p grantBatchPlan) document() map[string]any {
	raw, _ := json.Marshal(p)
	var doc map[string]any
	_ = json.Unmarshal(raw, &doc)
	delete(doc, "signature")
	return doc
}

func (s *Server) grantBatchPreview(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var req struct {
		SchemaVersion string             `json:"schema_version"`
		ActorID       string             `json:"actor_id"`
		Targets       []grantBatchTarget `json:"targets"`
	}
	if !readStrictRequestLimit(w, r, &req, "grant_batch_invalid", 32<<10, "schema_version", "actor_id", "targets") {
		return
	}
	if req.SchemaVersion != "grant-batch-revoke-request/v1" || strings.TrimSpace(req.ActorID) == "" || utf8.RuneCountInString(req.ActorID) > 128 || len(req.Targets) == 0 || len(req.Targets) > 50 {
		writeJSON(w, 400, map[string]string{"error": "grant_batch_invalid"})
		return
	}
	seen := map[string]bool{}
	plan := grantBatchPlan{SchemaVersion: "grant-batch-revoke-plan/v1", SigningSchema: signing.SchemaLocalCanonicalV1, ActorID: strings.TrimSpace(req.ActorID), Action: "revoke", ExpiresAt: time.Now().UTC().Add(5 * time.Minute).Format(time.RFC3339Nano)}
	for _, target := range req.Targets {
		if target.GrantID == "" || len(target.GrantID) > 200 || seen[target.GrantID] || target.ExpectedRevision == nil || *target.ExpectedRevision < 0 {
			writeJSON(w, 400, map[string]string{"error": "grant_batch_invalid"})
			return
		}
		seen[target.GrantID] = true
		g, seq, err := s.d.Store.GetGrantWithSeq(target.GrantID)
		if err != nil || !grant.Verify(s.d.Key.Public(), *g) || seq != *target.ExpectedRevision {
			writeJSON(w, 409, map[string]string{"error": "grant_batch_source_changed"})
			return
		}
		if _, err := grant.Revoke(*g, s.d.Key); err != nil {
			writeJSON(w, 409, map[string]string{"error": "grant_batch_not_revocable"})
			return
		}
		plan.Items = append(plan.Items, grantBatchItem{GrantID: g.GrantID, ExpectedRevision: seq, SubjectID: g.Subject.ID, Platform: g.Platform, Status: g.Status})
	}
	id, err := newSessionToken()
	if err != nil {
		writeJSON(w, 500, map[string]string{"error": "grant_batch_unavailable"})
		return
	}
	plan.BatchID = "gb-" + id
	plan.Signature, err = s.d.Key.SignCanonical(plan.document())
	if err != nil {
		writeJSON(w, 500, map[string]string{"error": "grant_batch_unavailable"})
		return
	}
	writeJSON(w, 200, plan)
}

func (s *Server) grantBatchApply(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var req struct {
		SchemaVersion string         `json:"schema_version"`
		Confirmed     bool           `json:"confirmed"`
		Plan          grantBatchPlan `json:"plan"`
	}
	if !readStrictRequestLimit(w, r, &req, "grant_batch_invalid", 64<<10, "schema_version", "confirmed", "plan") {
		return
	}
	p := req.Plan
	expires, err := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	if req.SchemaVersion != "grant-batch-revoke-apply/v1" || !req.Confirmed || p.SchemaVersion != "grant-batch-revoke-plan/v1" || p.SigningSchema != signing.SchemaLocalCanonicalV1 || p.Action != "revoke" || len(p.Items) == 0 || len(p.Items) > 50 || err != nil || !time.Now().Before(expires) || signing.VerifyDocument(s.d.Key.Public(), p.document(), p.Signature) != nil {
		writeJSON(w, 400, map[string]string{"error": "grant_batch_plan_invalid_or_expired"})
		return
	}
	seen := map[string]bool{}
	for _, item := range p.Items {
		if seen[item.GrantID] || item.GrantID == "" || item.ExpectedRevision < 0 {
			writeJSON(w, 400, map[string]string{"error": "grant_batch_invalid"})
			return
		}
		seen[item.GrantID] = true
	}
	results := make([]grantBatchResultItem, 0, len(p.Items))
	for _, item := range p.Items {
		results = append(results, s.revokeBatchItem(p, item))
	}
	s.invalidateProjection("grant_batch_revoke")
	writeJSON(w, 200, map[string]any{"schema_version": "grant-batch-revoke-result/v1", "batch_id": p.BatchID, "items": results})
}

func (s *Server) revokeBatchItem(p grantBatchPlan, item grantBatchItem) grantBatchResultItem {
	result := grantBatchResultItem{GrantID: item.GrantID, Status: "unavailable"}
	g, seq, err := s.d.Store.GetGrantWithSeq(item.GrantID)
	if err != nil || !grant.Verify(s.d.Key.Public(), *g) {
		return result
	}
	result.StateRevision = &seq
	if g.Status == "revoked" {
		// Read-only replay: never claim which operation performed this revocation.
		result.Status = "already_revoked"
		return result
	}
	if seq != item.ExpectedRevision || g.Subject.ID != item.SubjectID || g.Platform != item.Platform || g.Status != item.Status {
		result.Status = "conflict"
		return result
	}
	out, err := grant.Revoke(*g, s.d.Key)
	if err != nil {
		result.Status = "conflict"
		return result
	}
	next, err := s.d.Store.CommitGrant(state.GrantCommit{Grant: out, ExpectedRevision: seq, Audit: &state.AuditEvent{
		At: time.Now().UTC().Format(time.RFC3339Nano), Event: "grant_revoke", Target: g.GrantID, ActorID: p.ActorID, Note: "batch=" + p.BatchID,
	}})
	if err != nil {
		result.StateRevision = nil // An incomplete commit is not a confirmed state.
		if errors.Is(err, state.ErrRevisionConflict) {
			result.Status = "conflict"
		}
		return result
	}
	result.Status, result.StateRevision = "revoked", &next
	return result
}
