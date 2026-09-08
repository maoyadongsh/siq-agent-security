package server

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/provenance"
)

type observerSession struct {
	ID      string
	Source  effectevidence.Source
	Scope   provenance.Scope
	Expires time.Time
}

func tokenDigest(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

// Caller holds observerMu through submission, so completed revocation is final.
func (s *Server) observer(token string, now time.Time) (observerSession, bool) {
	digest := tokenDigest(token)
	o, ok := s.observers[digest]
	if !ok || !now.Before(o.Expires) {
		delete(s.observers, digest)
		return observerSession{}, false
	}
	revoked, err := s.effects.ObserverRevoked(digest)
	if err != nil || revoked {
		return observerSession{}, false
	}
	return o, true
}
func effectError(w http.ResponseWriter, err error) {
	code, status := "effect_evidence_state_unavailable", 500
	for _, known := range []error{effectevidence.ErrInvalid, effectevidence.ErrCorrelation, effectevidence.ErrObserver, effectevidence.ErrConflict, effectevidence.ErrNotFound, effectevidence.ErrCapacity} {
		if errors.Is(err, known) {
			code, status = known.Error(), 400
			break
		}
	}
	if errors.Is(err, effectevidence.ErrConflict) {
		status = 409
	}
	if errors.Is(err, effectevidence.ErrNotFound) {
		status = 404
	}
	if errors.Is(err, effectevidence.ErrCapacity) {
		status = 503
	}
	if errors.Is(err, effectevidence.ErrObserver) {
		status = 403
	}
	writeJSON(w, status, map[string]string{"error": code, "reason_code": code})
}
func readEffect(w http.ResponseWriter, r *http.Request, out any) bool {
	d := json.NewDecoder(http.MaxBytesReader(w, r.Body, 64<<10))
	d.DisallowUnknownFields()
	if d.Decode(out) != nil {
		effectError(w, effectevidence.ErrInvalid)
		return false
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		effectError(w, effectevidence.ErrInvalid)
		return false
	}
	return true
}
func (s *Server) effectObservers(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		w.WriteHeader(405)
		return
	}
	var body struct {
		Source    effectevidence.Source `json:"source"`
		Scope     provenance.Scope      `json:"scope"`
		ExpiresIn int                   `json:"expires_in"`
	}
	if !readEffect(w, r, &body) {
		return
	}
	allowed := map[string]string{"host_observer": "host_independent", "openshell": "host_independent", "provider_audit": "external_independent", "test_oracle": "external_independent"}
	if allowed[body.Source.Type] == "" || allowed[body.Source.Type] != body.Source.Independence || strings.TrimSpace(body.Source.SourceID) == "" || len(body.Source.SourceID) > 256 || body.ExpiresIn < 1 || body.ExpiresIn > 3600 {
		effectError(w, effectevidence.ErrInvalid)
		return
	}
	for _, v := range []string{body.Scope.Platform, body.Scope.SessionID, body.Scope.AgentID, body.Scope.TaskID} {
		if strings.TrimSpace(v) == "" || len(v) > 256 {
			effectError(w, effectevidence.ErrInvalid)
			return
		}
	}
	s.observerMu.Lock()
	defer s.observerMu.Unlock()
	now := time.Now()
	for digest, o := range s.observers {
		if !now.Before(o.Expires) {
			delete(s.observers, digest)
		}
	}
	if len(s.observers) >= 128 {
		effectError(w, effectevidence.ErrCapacity)
		return
	}
	token, err := newSessionToken()
	if err != nil {
		effectError(w, err)
		return
	}
	digest := tokenDigest(token)
	id := "observer-" + digest[:32]
	s.observers[digest] = observerSession{ID: id, Source: body.Source, Scope: body.Scope, Expires: now.Add(time.Duration(body.ExpiresIn) * time.Second)}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, 201, map[string]any{"observer_id": id, "token": token, "expires_in": body.ExpiresIn, "scope": "effect_observe"})
}
func (s *Server) revokeEffectObserver(w http.ResponseWriter, r *http.Request) {
	if r.Method != "DELETE" {
		w.WriteHeader(405)
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/v1/effect-observers/")
	s.observerMu.Lock()
	defer s.observerMu.Unlock()
	for digest, o := range s.observers {
		if o.ID == id {
			if _, err := s.effects.RevokeObserver(digest, time.Now()); err != nil {
				effectError(w, err)
				return
			}
			delete(s.observers, digest)
			w.WriteHeader(204)
			return
		}
	}
	w.WriteHeader(404)
}
func (s *Server) submitEffect(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		w.WriteHeader(405)
		return
	}
	var e effectevidence.Evidence
	if !readEffect(w, r, &e) {
		return
	}
	s.observerMu.Lock()
	defer s.observerMu.Unlock()
	now := time.Now()
	o, ok := s.observer(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "), now)
	if !ok {
		effectError(w, effectevidence.ErrObserver)
		return
	}
	a, err := s.d.Engine.EffectAction(e.ActionID, e.DecisionReceiptID)
	if err != nil {
		effectError(w, err)
		return
	}
	if o.Scope != (provenance.Scope{Platform: a.Platform, SessionID: a.SessionID, AgentID: a.AgentID, TaskID: a.TaskID}) {
		effectError(w, effectevidence.ErrObserver)
		return
	}
	record, err := s.effects.Submit(e, a, o.Source, now)
	if err != nil {
		effectError(w, err)
		return
	}
	writeJSON(w, 201, record)
}
func (s *Server) getEffect(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" {
		w.WriteHeader(405)
		return
	}
	record, err := s.effects.Get(strings.TrimPrefix(r.URL.Path, "/v1/effect-evidence/"), time.Now())
	if err != nil {
		effectError(w, err)
		return
	}
	writeJSON(w, 200, record)
}
func (s *Server) actionEffects(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" {
		w.WriteHeader(405)
		return
	}
	path := strings.TrimPrefix(r.URL.Path, "/v1/actions/")
	if !strings.HasSuffix(path, "/effect-evidence") {
		w.WriteHeader(404)
		return
	}
	id := strings.TrimSuffix(path, "/effect-evidence")
	records, err := s.effects.ForAction(id, time.Now())
	if err != nil {
		effectError(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"items": records})
}
