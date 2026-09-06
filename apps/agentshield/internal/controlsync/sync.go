// Package controlsync uploads a local inventory batch to Control API Edge
// ingest (dev-spec §2.4). It never writes admissions, grants or receipts.
package controlsync

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/inventory"
	"siq-agent-security/apps/agentshield/internal/signing"
)

const maxCandidateID = 256

// Creds are Edge device credentials. Empty Identity/Secret/TaskID means skip.
type Creds struct {
	ControlAPI string
	Identity   string
	Secret     string
	TaskID     string
}

// Result is one sync attempt.
type Result struct {
	Skipped    bool   `json:"skipped"`
	Reason     string `json:"reason,omitempty"`
	StatusCode int    `json:"status_code,omitempty"`
	Candidates int    `json:"candidates,omitempty"`
	Evidence   int    `json:"evidence,omitempty"`
	Body       string `json:"body,omitempty"`
}

// Skip reports whether sync should no-op (default: not enrolled).
func (c Creds) Skip() bool {
	return strings.TrimSpace(c.Identity) == "" || strings.TrimSpace(c.Secret) == "" || strings.TrimSpace(c.TaskID) == "" || strings.TrimSpace(c.ControlAPI) == ""
}

// Push posts candidates+evidence. HTTP client may be nil.
func Push(rep *inventory.Report, key *signing.Key, c Creds, now time.Time, client *http.Client) (Result, error) {
	if c.Skip() {
		return Result{Skipped: true, Reason: "missing Edge enrollment (identity/secret/task_id); local decisions unchanged"}, nil
	}
	if key == nil {
		return Result{}, errors.New("controlsync: signing key required")
	}
	if rep == nil {
		return Result{}, errors.New("controlsync: inventory report required")
	}
	if now.IsZero() {
		now = time.Now().UTC()
	}
	batch, nCand, nEv, err := buildBatch(rep, key, c.Identity, c.TaskID, now)
	if err != nil {
		return Result{}, err
	}
	if nCand == 0 && nEv == 0 {
		return Result{Skipped: true, Reason: "empty inventory batch; local decisions unchanged"}, nil
	}
	raw, err := json.Marshal(batch)
	if err != nil {
		return Result{}, err
	}
	if client == nil {
		client = &http.Client{Timeout: 15 * time.Second}
	}
	url := strings.TrimRight(c.ControlAPI, "/") + "/edge/v1/batches"
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(raw))
	if err != nil {
		return Result{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.Secret)
	req.Header.Set("X-Edge-Identity", c.Identity)
	resp, err := client.Do(req)
	if err != nil {
		return Result{}, fmt.Errorf("controlsync: upload failed; local decisions unchanged: %w", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<10))
	out := Result{StatusCode: resp.StatusCode, Candidates: nCand, Evidence: nEv, Body: strings.TrimSpace(string(body))}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return out, fmt.Errorf("controlsync: HTTP %d; local decisions unchanged", resp.StatusCode)
	}
	return out, nil
}

func buildBatch(rep *inventory.Report, key *signing.Key, identity, taskID string, now time.Time) (map[string]any, int, int, error) {
	stamp := now.UTC().Format(time.RFC3339)
	evByID := map[string]map[string]any{}
	for _, ev := range rep.Evidence {
		if ev.EvidenceID == "" {
			continue
		}
		item := evidenceMap(ev, identity, stamp, key)
		evByID[ev.EvidenceID] = item
	}
	var cands []map[string]any
	used := map[string]bool{}
	for _, c := range rep.Candidates {
		id := c.CandidateID
		if len(id) > maxCandidateID {
			continue
		}
		status := c.Status
		switch status {
		case "needs_review":
		case "dismissed":
		default:
			status = "candidate"
		}
		ids := make([]string, 0, len(c.EvidenceIDs))
		for _, eid := range c.EvidenceIDs {
			if _, ok := evByID[eid]; ok {
				ids = append(ids, eid)
				used[eid] = true
			}
		}
		if len(ids) == 0 {
			continue
		}
		row := map[string]any{
			"candidate_id":   id,
			"source_type":    c.SourceType,
			"source_locator": c.SourceLocator,
			"discovered_at":  c.DiscoveredAt,
			"name":           c.Name,
			"framework":      c.Framework,
			"evidence_ids":   ids,
			"confidence":     c.Confidence,
			"status":         status,
		}
		if c.ArtifactDigest != "" {
			row["artifact_digest"] = c.ArtifactDigest
		}
		if len(c.Attributes) > 0 {
			row["attributes"] = c.Attributes
		}
		cands = append(cands, row)
	}
	var evs []map[string]any
	for id, item := range evByID {
		if used[id] {
			evs = append(evs, item)
		}
	}
	batch := map[string]any{
		"task_id":          taskID,
		"candidates":       cands,
		"evidence":         evs,
		"permission_facts": []any{},
	}
	sig, err := signBatch(key, batch)
	if err != nil {
		return nil, 0, 0, err
	}
	batch["signature"] = sig
	return batch, len(cands), len(evs), nil
}

func evidenceMap(ev admission.Evidence, identity, stamp string, key *signing.Key) map[string]any {
	m := map[string]any{
		"evidence_id":       ev.EvidenceID,
		"source_type":       ev.SourceType,
		"source_locator":    ev.SourceLocator,
		"observed_at":       ev.ObservedAt,
		"collected_at":      stamp,
		"collector_id":      identity,
		"connector_version": ev.ConnectorVersion,
		"content_hash":      ev.ContentHash,
		"redaction_profile": ev.RedactionProfile,
		"classification":    ev.Classification,
		"signature":         "",
	}
	if ev.SubjectRef != nil {
		m["subject_ref"] = *ev.SubjectRef
	}
	if ev.PayloadRef != nil {
		m["payload_ref"] = *ev.PayloadRef
	}
	if m["redaction_profile"] == "" {
		m["redaction_profile"] = "siq.redaction.v1"
	}
	if m["classification"] == "" {
		m["classification"] = "internal"
	}
	if m["connector_version"] == "" {
		m["connector_version"] = "0.0.0-dev"
	}
	m["signature"] = ""
	sig, _ := signCanonical(key, m)
	m["signature"] = sig
	return m
}

func signCanonical(key *signing.Key, doc map[string]any) (string, error) {
	msg, err := canon.Marshal(doc)
	if err != nil {
		return "", err
	}
	return key.SignBytes(msg), nil
}

func signBatch(key *signing.Key, batch map[string]any) (string, error) {
	clone := map[string]any{}
	raw, err := json.Marshal(batch)
	if err != nil {
		return "", err
	}
	if err := json.Unmarshal(raw, &clone); err != nil {
		return "", err
	}
	delete(clone, "signature")
	return signCanonical(key, clone)
}
