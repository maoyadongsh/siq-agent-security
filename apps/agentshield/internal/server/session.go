package server

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"fmt"
	"net/http"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/state"
)

type refreshSession struct {
	Access  string
	Expires time.Time
}

func newPairingCode() (string, error) {
	var raw [8]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return "", err
	}
	h := hex.EncodeToString(raw[:])
	return h[:4] + "-" + h[4:8] + "-" + h[8:12] + "-" + h[12:], nil
}

func (s *Server) sessionCookieName() string {
	return fmt.Sprintf("siq_session_%d", s.listenPort())
}

func (s *Server) setSessionCookie(w http.ResponseWriter, r *http.Request, value string, maxAge int) {
	http.SetCookie(w, &http.Cookie{
		Name: s.sessionCookieName(), Value: value, Path: "/v1/session",
		HttpOnly: true, SameSite: http.SameSiteStrictMode, Secure: r.TLS != nil, MaxAge: maxAge,
	})
}

// Caller holds sessMu. Refresh credentials never authorize an admin mutation.
func (s *Server) pruneSessionsLocked(now time.Time) {
	for access, expires := range s.sessions {
		if !now.Before(expires) {
			delete(s.sessions, access)
		}
	}
	for hash, refresh := range s.refreshSessions {
		if _, ok := s.sessions[refresh.Access]; !ok || !now.Before(refresh.Expires) {
			delete(s.refreshSessions, hash)
		}
	}
}

func (s *Server) restoreSession(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	if r.Header.Get("X-SIQ-Session") != "1" {
		writeJSON(w, 403, map[string]any{"error": "session header required"})
		return
	}
	if r.Header.Get("Authorization") != "" {
		writeJSON(w, 403, map[string]any{"error": "restore accepts only its recovery cookie"})
		return
	}
	cookie, err := r.Cookie(s.sessionCookieName())
	if err != nil || len(cookie.Value) != 64 {
		writeJSON(w, 401, map[string]any{"error": "pairing required"})
		return
	}
	s.sessMu.Lock()
	defer s.sessMu.Unlock()
	now := time.Now()
	s.pruneSessionsLocked(now)
	refresh, ok := s.refreshSessions[sha256.Sum256([]byte(cookie.Value))]
	remaining := int(refresh.Expires.Sub(now).Seconds())
	if !ok || remaining < 1 {
		s.setSessionCookie(w, r, "", -1)
		writeJSON(w, 401, map[string]any{"error": "pairing required"})
		return
	}
	// Fixed lifetime: opening another tab or reloading never extends authorization.
	writeJSON(w, 200, map[string]any{
		"schema_version": "local-admin-session/v1", "session": refresh.Access,
		"expires_in": remaining, "scope": "admin",
	})
}

func (s *Server) logoutSession(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	access := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	s.sessMu.Lock()
	delete(s.sessions, access)
	s.pruneSessionsLocked(time.Now())
	s.sessMu.Unlock()
	s.setSessionCookie(w, r, "", -1)
	writeJSON(w, 200, map[string]any{"schema_version": "local-logout/v1", "signed_out": true})
}

// Only a same-user local CLI may mint another one-time code. It cannot mint a
// Grant or obtain a bearer session without a separate pairing exchange.
func (s *Server) renewPairing(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	if r.Header.Get("X-SIQ-Local-CLI") != "1" || r.Header.Get("Origin") != "" ||
		r.Header.Get("Sec-Fetch-Site") != "" || r.Header.Get("Sec-Fetch-Mode") != "" ||
		r.Header.Get("Sec-Fetch-Dest") != "" || r.Header.Get("Sec-Fetch-User") != "" {
		writeJSON(w, 403, map[string]any{"error": "local CLI required"})
		return
	}
	presented := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	if len(s.d.RecoveryToken) != 64 || s.d.RecoveryToken == s.d.Token ||
		!strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") ||
		subtle.ConstantTimeCompare([]byte(presented), []byte(s.d.RecoveryToken)) != 1 {
		writeJSON(w, 401, map[string]any{"error": "recovery credential required"})
		return
	}
	code, err := newPairingCode()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "pairing unavailable"})
		return
	}
	s.pairMu.Lock()
	defer s.pairMu.Unlock()
	if err := s.d.Store.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339), Event: "admin_pairing_renewed", ActorID: "local-cli"}); err != nil {
		writeJSON(w, 500, map[string]any{"error": "audit unavailable"})
		return
	}
	s.pairDisplay, s.pairHash = code, sha256.Sum256([]byte(normalizePairing(code)))
	s.pairDeadline, s.pairAttempts, s.pairConsumed = time.Now().Add(pairingTTL), 0, false
	writeJSON(w, 200, map[string]any{
		"schema_version": "local-pairing/v1", "code": code, "expires_in": int(pairingTTL.Seconds()),
	})
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	writeJSON(w, 200, map[string]any{
		"schema_version": "local-service-health/v1", "product": "siq-agent-security",
		"version": s.d.Version, "local_mode": true, "status": "ready",
	})
}

func (s *Server) instanceHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		writeJSON(w, 405, map[string]any{"error": "GET required"})
		return
	}
	writeJSON(w, 200, map[string]any{
		"schema_version": "local-service-instance-health/v1", "product": "siq-agent-security",
		"version": s.d.Version, "local_mode": true, "status": "ready",
		"state_directory_id": s.stateDirectoryID,
	})
}
