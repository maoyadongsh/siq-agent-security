package server

import (
	"errors"
	"net/http"
	"regexp"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

var fileObservationID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)
var fileExpectedDigest = regexp.MustCompile(`^[0-9a-f]{64}$`)

type pendingFileObservation struct {
	Before                                     effectevidence.FileSnapshot
	ActionID, ReceiptID, ExpectedDigest, Owner string
	MaxBytes                                   int64
	Expires                                    time.Time
	Completed                                  bool
}

func fileResource(path string) (string, error) {
	if len(path) > 4096 {
		return "", effectevidence.ErrInvalid
	}
	p, err := runtimeaction.NormalizeResource("filesystem", path)
	if err != nil || p != path {
		return "", effectevidence.ErrInvalid
	}
	refs := runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "filesystem", Value: p}})
	return effectevidence.ResourceReference(refs[0])
}
func (s *Server) fileAction(o observerSession, actionID, receiptID string) (effectevidence.Action, error) {
	if o.Source.Type != "host_observer" || o.Source.Independence != "host_independent" {
		return effectevidence.Action{}, effectevidence.ErrObserver
	}
	a, err := s.d.Engine.EffectAction(actionID, receiptID)
	if err != nil {
		return a, err
	}
	if o.Scope != (provenance.Scope{Platform: a.Platform, SessionID: a.SessionID, AgentID: a.AgentID, TaskID: a.TaskID}) {
		return effectevidence.Action{}, effectevidence.ErrObserver
	}
	for _, effect := range a.Effects {
		if effect == "file.write" {
			return a, nil
		}
	}
	return effectevidence.Action{}, effectevidence.ErrCorrelation
}
func (s *Server) beginFileObservation(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		w.WriteHeader(405)
		return
	}
	var body struct {
		ID        string `json:"observation_id"`
		ActionID  string `json:"action_id"`
		ReceiptID string `json:"decision_receipt_id"`
		Path      string `json:"path"`
		Expected  string `json:"expected_digest"`
		MaxBytes  int64  `json:"max_bytes"`
	}
	if !readEffect(w, r, &body) {
		return
	}
	if !fileObservationID.MatchString(body.ID) || !fileExpectedDigest.MatchString(body.Expected) || body.MaxBytes < 1 || body.MaxBytes > effectevidence.MaxFileBytes {
		effectError(w, effectevidence.ErrInvalid)
		return
	}
	s.observerMu.Lock()
	defer s.observerMu.Unlock()
	now := time.Now()
	token := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	owner := tokenDigest(token)
	o, ok := s.observer(token, now)
	if !ok {
		effectError(w, effectevidence.ErrObserver)
		return
	}
	a, err := s.fileAction(o, body.ActionID, body.ReceiptID)
	if err != nil {
		effectError(w, err)
		return
	}
	ref, err := fileResource(body.Path)
	if err != nil {
		effectError(w, err)
		return
	}
	matched := false
	for _, resource := range a.Resources {
		value, _ := effectevidence.ResourceReference(resource)
		if value == ref {
			matched = true
		}
	}
	if !matched {
		effectError(w, effectevidence.ErrCorrelation)
		return
	}
	for id, p := range s.fileObservations {
		_, active := s.observers[p.Owner]
		if !active || !now.Before(p.Expires) {
			delete(s.fileObservations, id)
		}
	}
	if p, exists := s.fileObservations[body.ID]; exists {
		if p.Owner != owner || p.ActionID != a.ActionID || p.ReceiptID != a.DecisionReceiptID || p.Before.ResourceRef != ref || p.ExpectedDigest != body.Expected || p.MaxBytes != body.MaxBytes {
			effectError(w, effectevidence.ErrConflict)
			return
		}
		writeJSON(w, 200, map[string]any{"observation_id": body.ID, "before": p.Before, "completed": p.Completed})
		return
	}
	if _, err = s.effects.Get(body.ID, now); !errors.Is(err, effectevidence.ErrNotFound) {
		if err == nil {
			err = effectevidence.ErrConflict
		}
		effectError(w, err)
		return
	}
	if len(s.fileObservations) >= 128 {
		effectError(w, effectevidence.ErrCapacity)
		return
	}
	persisted, pendingErr := s.effects.GetPendingFile(body.ID)
	if pendingErr == nil {
		expires, parseErr := time.Parse(time.RFC3339Nano, persisted.ExpiresAt)
		if parseErr != nil || !now.Before(expires) || persisted.OwnerDigest != owner || persisted.Scope != o.Scope || persisted.Source != o.Source || persisted.ActionID != a.ActionID || persisted.ReceiptID != a.DecisionReceiptID || persisted.Before.ResourceRef != ref || persisted.ExpectedDigest != body.Expected || persisted.MaxBytes != body.MaxBytes {
			effectError(w, effectevidence.ErrConflict)
			return
		}
		s.fileObservations[body.ID] = pendingFileObservation{Before: persisted.Before, ActionID: persisted.ActionID, ReceiptID: persisted.ReceiptID, ExpectedDigest: persisted.ExpectedDigest, Owner: owner, MaxBytes: persisted.MaxBytes, Expires: expires}
		writeJSON(w, 200, map[string]any{"observation_id": body.ID, "before": persisted.Before, "completed": false})
		return
	}
	if !errors.Is(pendingErr, effectevidence.ErrNotFound) {
		effectError(w, pendingErr)
		return
	}
	before, err := effectevidence.CaptureFile(body.Path, body.MaxBytes)
	if err != nil {
		effectError(w, effectevidence.ErrInvalid)
		return
	}
	_, err = s.effects.SavePendingFile(effectevidence.PendingFile{SchemaVersion: "file-observation-pending/v1", ID: body.ID, ActionID: a.ActionID, ReceiptID: a.DecisionReceiptID, Scope: o.Scope, Source: o.Source, Before: before, OwnerDigest: owner, ExpectedDigest: body.Expected, MaxBytes: body.MaxBytes, ExpiresAt: o.Expires.UTC().Format(time.RFC3339Nano), SigningSchema: "local_canonical/v1"})
	if err != nil {
		effectError(w, err)
		return
	}
	s.fileObservations[body.ID] = pendingFileObservation{Before: before, ActionID: a.ActionID, ReceiptID: a.DecisionReceiptID, ExpectedDigest: body.Expected, Owner: owner, MaxBytes: body.MaxBytes, Expires: o.Expires}
	writeJSON(w, 201, map[string]any{"observation_id": body.ID, "before": before, "completed": false})
}
func (s *Server) finishFileObservation(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		w.WriteHeader(405)
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/v1/file-observations/")
	if !strings.HasSuffix(id, "/finish") {
		w.WriteHeader(404)
		return
	}
	id = strings.TrimSuffix(id, "/finish")
	var body struct {
		Path string `json:"path"`
	}
	if !readEffect(w, r, &body) {
		return
	}
	s.observerMu.Lock()
	defer s.observerMu.Unlock()
	now := time.Now()
	token := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	o, ok := s.observer(token, now)
	if !ok {
		effectError(w, effectevidence.ErrObserver)
		return
	}
	p, ok := s.fileObservations[id]
	if !ok || !now.Before(p.Expires) {
		effectError(w, effectevidence.ErrNotFound)
		return
	}
	if p.Owner != tokenDigest(token) {
		effectError(w, effectevidence.ErrObserver)
		return
	}
	a, err := s.fileAction(o, p.ActionID, p.ReceiptID)
	if err != nil {
		effectError(w, err)
		return
	}
	ref, err := fileResource(body.Path)
	if err != nil || ref != p.Before.ResourceRef {
		effectError(w, effectevidence.ErrCorrelation)
		return
	}
	if p.Completed {
		record, err := s.effects.Get(id, now)
		if err != nil {
			effectError(w, err)
			return
		}
		writeJSON(w, 200, record)
		return
	}
	after, err := effectevidence.CaptureFile(body.Path, p.MaxBytes)
	if err != nil {
		effectError(w, effectevidence.ErrInvalid)
		return
	}
	material, err := effectevidence.FileWrite(p.Before, after, p.ExpectedDigest)
	if err != nil {
		effectError(w, effectevidence.ErrInvalid)
		return
	}
	record, err := s.effects.SubmitFile(id, material, a, o.Source, time.Now())
	if err != nil {
		effectError(w, err)
		return
	}
	p.Completed = true
	s.fileObservations[id] = p
	writeJSON(w, 201, record)
}
