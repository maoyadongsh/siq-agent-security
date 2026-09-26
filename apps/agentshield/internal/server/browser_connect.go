package server

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"time"

	"siq-agent-security/apps/agentshield/internal/state"
)

type browserConnectRequest struct {
	Proof    [32]byte
	Expires  time.Time
	Approved bool
}

var connectIDPattern = regexp.MustCompile(`^[a-f0-9]{32}$`)

func browserConnectHeader(w http.ResponseWriter, r *http.Request) bool {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return false
	}
	if r.Header.Get("X-SIQ-Session") != "1" || r.Header.Get("Authorization") != "" {
		writeJSON(w, 403, map[string]any{"error": "browser session header required"})
		return false
	}
	return true
}

func (s *Server) connectCookieName() string { return fmt.Sprintf("siq_connect_%d", s.listenPort()) }
func (s *Server) setConnectCookie(w http.ResponseWriter, r *http.Request, proof string, age int) {
	http.SetCookie(w, &http.Cookie{Name: s.connectCookieName(), Value: proof, Path: "/v1/session/connect",
		HttpOnly: true, SameSite: http.SameSiteStrictMode, Secure: r.TLS != nil, MaxAge: age})
}

// Caller holds sessMu. Request IDs are public locators; only the independent
// browser cookie can claim a locally approved request.
func (s *Server) pruneConnectRequests(now time.Time) {
	for id, request := range s.connectRequests {
		if !now.Before(request.Expires) {
			delete(s.connectRequests, id)
		}
	}
}

func connectReply(w http.ResponseWriter, id, status string, expires time.Time) {
	remaining := max(0, min(300, int(time.Until(expires).Seconds())))
	writeJSON(w, 200, map[string]any{"schema_version": "local-browser-connect/v1", "request_id": id, "status": status, "expires_in": remaining})
}

func (s *Server) createBrowserConnect(w http.ResponseWriter, r *http.Request) {
	if !browserConnectHeader(w, r) {
		return
	}
	id, err := newSessionToken()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "connection unavailable"})
		return
	}
	id = id[:32]
	proof, err := newSessionToken()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "connection unavailable"})
		return
	}
	s.sessMu.Lock()
	defer s.sessMu.Unlock()
	s.pruneConnectRequests(time.Now())
	if s.connectRequests == nil {
		s.connectRequests = make(map[string]browserConnectRequest)
	}
	if old, err := r.Cookie(s.connectCookieName()); err == nil && len(old.Value) == 64 {
		hash := sha256.Sum256([]byte(old.Value))
		for previous, request := range s.connectRequests {
			if request.Proof == hash {
				delete(s.connectRequests, previous)
			}
		}
	}
	if len(s.connectRequests) >= 32 {
		writeJSON(w, 429, map[string]any{"error": "too many connection requests"})
		return
	}
	request := browserConnectRequest{Proof: sha256.Sum256([]byte(proof)), Expires: time.Now().Add(pairingTTL)}
	s.connectRequests[id] = request
	s.setConnectCookie(w, r, proof, 300)
	connectReply(w, id, "pending", request.Expires)
}

func readConnectID(w http.ResponseWriter, r *http.Request) string {
	var body struct {
		RequestID string `json:"request_id"`
	}
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1024))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&body); err != nil || !connectIDPattern.MatchString(body.RequestID) {
		writeJSON(w, 400, map[string]any{"error": "valid request_id required"})
		return ""
	}
	if decoder.Decode(new(any)) != io.EOF {
		writeJSON(w, 400, map[string]any{"error": "single request object required"})
		return ""
	}
	return body.RequestID
}

func (s *Server) approveBrowserConnect(w http.ResponseWriter, r *http.Request) {
	if !s.requireRecoveryCLI(w, r) {
		return
	}
	id := readConnectID(w, r)
	if id == "" {
		return
	}
	s.sessMu.Lock()
	defer s.sessMu.Unlock()
	s.pruneConnectRequests(time.Now())
	request, ok := s.connectRequests[id]
	if !ok {
		writeJSON(w, 410, map[string]any{"error": "connection expired or absent"})
		return
	}
	if !request.Approved {
		if err := s.d.Store.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339), Event: "browser_connection_approved", ActorID: "local-cli"}); err != nil {
			writeJSON(w, 500, map[string]any{"error": "audit unavailable"})
			return
		}
		request.Approved = true
		s.connectRequests[id] = request
	}
	connectReply(w, id, "approved", request.Expires)
}

func (s *Server) cancelBrowserConnect(w http.ResponseWriter, r *http.Request) {
	s.browserConnectResult(w, r, true)
}
func (s *Server) pollBrowserConnect(w http.ResponseWriter, r *http.Request) {
	s.browserConnectResult(w, r, false)
}
func (s *Server) browserConnectResult(w http.ResponseWriter, r *http.Request, cancel bool) {
	if !browserConnectHeader(w, r) {
		return
	}
	id := readConnectID(w, r)
	if id == "" {
		return
	}
	cookie, err := r.Cookie(s.connectCookieName())
	if err != nil || len(cookie.Value) != 64 {
		writeJSON(w, 401, map[string]any{"error": "connection cookie required"})
		return
	}
	s.sessMu.Lock()
	defer s.sessMu.Unlock()
	s.pruneConnectRequests(time.Now())
	request, ok := s.connectRequests[id]
	if !ok {
		writeJSON(w, 410, map[string]any{"error": "connection expired or absent"})
		return
	}
	if sha256.Sum256([]byte(cookie.Value)) != request.Proof {
		writeJSON(w, 401, map[string]any{"error": "connection cookie mismatch"})
		return
	}
	if cancel {
		delete(s.connectRequests, id)
		s.setConnectCookie(w, r, "", -1)
		connectReply(w, id, "cancelled", time.Now())
		return
	}
	if !request.Approved {
		connectReply(w, id, "pending", request.Expires)
		return
	}
	access, err := newSessionToken()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "session unavailable"})
		return
	}
	refresh, err := newSessionToken()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "session unavailable"})
		return
	}
	if err := s.d.Store.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339), Event: "browser_connection_claimed", ActorID: "local-browser"}); err != nil {
		writeJSON(w, 500, map[string]any{"error": "audit unavailable"})
		return
	}
	expires := time.Now().Add(adminSessionTTL)
	s.pruneSessionsLocked(time.Now())
	s.sessions[access] = expires
	s.refreshSessions[sha256.Sum256([]byte(refresh))] = refreshSession{Access: access, Expires: expires}
	delete(s.connectRequests, id)
	s.setConnectCookie(w, r, "", -1)
	s.setSessionCookie(w, r, refresh, int(adminSessionTTL.Seconds()))
	writeJSON(w, 200, map[string]any{"schema_version": "local-admin-session/v2", "session": access, "expires_in": int(adminSessionTTL.Seconds()), "scope": "admin"})
}
