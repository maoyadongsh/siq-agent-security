package completion

import (
	"crypto/ed25519"
	"errors"
	"sort"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
)

type Task struct {
	ID, IntentID, IntentDigest string
	Requirements               []Requirement
}
type Item struct {
	RequirementID string   `json:"requirement_id"`
	Status        string   `json:"status"`
	ReasonCode    string   `json:"reason_code"`
	EvidenceIDs   []string `json:"evidence_ids"`
}
type Result struct {
	SchemaVersion string   `json:"schema_version"`
	TaskID        string   `json:"task_id"`
	Status        string   `json:"status"`
	ReasonCode    string   `json:"reason_code"`
	Requirements  []Item   `json:"requirements"`
	IncidentIDs   []string `json:"incident_ids"`
}
type ActionLookup func(string, string) (effectevidence.Action, error)

var ErrEvidence = errors.New("completion_evidence_invalid")

// Evaluate expects Task to be projected from an already verified signed Intent.
// Records are verified again here; action authority comes only from the engine.
func Evaluate(task Task, records []effectevidence.Record, pub ed25519.PublicKey, lookup ActionLookup, now time.Time) (Result, error) {
	out := Result{SchemaVersion: "completion-status/v1", TaskID: task.ID, Status: "unknown", ReasonCode: "not_required", Requirements: []Item{}, IncidentIDs: []string{}}
	if !identifier.MatchString(task.ID) || !identifier.MatchString(task.IntentID) || !digest.MatchString(task.IntentDigest) || len(task.Requirements) > 128 || len(records) > effectevidence.MaxRecords || lookup == nil {
		return Result{}, ErrEvidence
	}
	seenReq := map[string]bool{}
	for _, r := range task.Requirements {
		if r.Validate() != nil || seenReq[r.RequirementID] {
			return Result{}, ErrRequirement
		}
		seenReq[r.RequirementID] = true
	}
	seen := map[string]bool{}
	relevant := []effectevidence.Record{}
	actions := map[string]effectevidence.Action{}
	for _, r := range records {
		if r.Verify(pub, now) != nil || seen[r.Evidence.EvidenceID] {
			return Result{}, ErrEvidence
		}
		seen[r.Evidence.EvidenceID] = true
		if r.TaskID != task.ID {
			continue
		}
		a, err := lookup(r.Evidence.ActionID, r.Evidence.DecisionReceiptID)
		if err != nil || a.ActionID != r.Evidence.ActionID || a.DecisionReceiptID != r.Evidence.DecisionReceiptID || a.TaskID != task.ID || a.IntentID != task.IntentID || a.IntentDigest != task.IntentDigest {
			return Result{}, ErrEvidence
		}
		relevant = append(relevant, r)
		actions[r.Evidence.EvidenceID] = a
		if r.FindingCode != "" {
			out.IncidentIDs = append(out.IncidentIDs, r.Evidence.EvidenceID)
		}
	}
	sort.Strings(out.IncidentIDs)
	if len(task.Requirements) == 0 {
		return out, nil
	}
	out.Status = "verified"
	out.ReasonCode = "effects_verified"
	for _, req := range task.Requirements {
		item := Item{RequirementID: req.RequirementID, Status: "incomplete", ReasonCode: "effect_evidence_missing", EvidenceIDs: []string{}}
		good, unknown, conflict, failed := false, false, false, false
		// Bounded by the already limited input records; do not mix different
		// attempts at the same requirement into one contradictory action.
		type actionKey struct{ action, receipt string }
		outcomes := map[actionKey]uint8{}
		for _, r := range relevant {
			e := r.Evidence
			if e.EffectType != req.EffectType || e.ResourceRef != req.ResourceRef {
				continue
			}
			item.EvidenceIDs = append(item.EvidenceIDs, e.EvidenceID)
			a := actions[e.EvidenceID]
			if r.FindingCode != "" || e.Result == "conflicting" {
				conflict = true
				continue
			}
			if e.Source.Independence != "host_independent" && e.Source.Independence != "external_independent" {
				unknown = true
				continue
			}
			if req.MinimumIndependence == "external_independent" && e.Source.Independence != "external_independent" {
				unknown = true
				continue
			}
			if e.Coverage == "unknown" || req.MinimumCoverage == "full" && e.Coverage != "full" {
				unknown = true
				continue
			}
			if e.ExecutionState == "failed" {
				failed = true
				if req.EffectType == "file.write" && r.FileObservation != nil || req.EffectType == "network.request" && r.NetworkObservation != nil {
					outcomes[actionKey{e.ActionID, e.DecisionReceiptID}] |= 2
				}
				continue
			}
			if e.ExecutionState != "completed" || e.Result == "unknown" || (req.EffectType == "file.write" && r.FileObservation == nil) || (req.EffectType == "network.request" && r.NetworkObservation == nil) {
				unknown = true
				continue
			}
			observed, _ := time.Parse(time.RFC3339Nano, e.ObservedAt)
			if !a.Authorized || (!a.AuthorizedAt.IsZero() && observed.Before(a.AuthorizedAt)) || e.Result != "expected" || !materialSatisfies(req, r) {
				conflict = true
				continue
			}
			matched := false
			effectMatch := false
			for _, ref := range a.Resources {
				value, err := effectevidence.ResourceReference(ref)
				if err == nil && value == req.ResourceRef {
					matched = true
				}
			}
			for _, effect := range a.Effects {
				if effect == req.EffectType {
					effectMatch = true
				}
			}
			if !matched || !effectMatch {
				return Result{}, ErrEvidence
			}
			good = true
			outcomes[actionKey{e.ActionID, e.DecisionReceiptID}] |= 1
		}
		for _, outcome := range outcomes {
			if outcome == 3 {
				conflict = true
			}
		}
		sort.Strings(item.EvidenceIDs)
		switch {
		case conflict:
			item.Status = "conflicting"
			item.ReasonCode = "effect_evidence_conflicting"
		case unknown:
			item.Status = "unknown"
			item.ReasonCode = "effect_evidence_insufficient"
		case failed:
			item.Status = "incomplete"
			item.ReasonCode = "effect_failed"
		case good:
			item.Status = "verified"
			item.ReasonCode = "effect_verified"
		}
		out.Requirements = append(out.Requirements, item)
		if rank(item.Status) > rank(out.Status) {
			out.Status = item.Status
			out.ReasonCode = item.ReasonCode
		}
	}
	if len(out.IncidentIDs) > 0 {
		out.Status = "conflicting"
		out.ReasonCode = "task_security_incident"
	}
	return out, nil
}
func rank(status string) int {
	switch status {
	case "conflicting":
		return 3
	case "unknown":
		return 2
	case "incomplete":
		return 1
	}
	return 0
}

func materialSatisfies(req Requirement, r effectevidence.Record) bool {
	if req.EffectType == "file.write" {
		m := r.FileObservation
		return m != nil && m.After.Exists && m.After.Digest == req.ExpectedDigest && m.ExpectedDigest == req.ExpectedDigest
	}
	m, e := r.NetworkObservation, req.ExpectedEndpoint
	return m != nil && e != nil && m.RequestedScheme == e.Scheme && m.RequestedHost == e.Host && m.RequestedPort == e.Port && m.Received.Scheme == e.Scheme && m.Received.Host == e.Host && m.Received.Port == e.Port && m.Received.RequestDigest == req.ExpectedDigest
}
