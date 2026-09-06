package server

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type capability uint8

const (
	capAdmin capability = 1 << iota
	capDecision
)

const (
	pairingTTL         = 5 * time.Minute
	pairingMaxAttempts = 5
	adminSessionTTL    = 12 * time.Hour
	testPairingCode    = "test-pair-0001"
)

func (s *Server) initPairing(supplied string) error {
	s.sessions = map[string]time.Time{}
	if strings.TrimSpace(supplied) != "" {
		norm := normalizePairing(supplied)
		if norm == "" {
			return errors.New("server: pairing code is empty")
		}
		s.pairDisplay = supplied
		s.pairHash = sha256.Sum256([]byte(norm))
		s.pairDeadline = time.Now().Add(pairingTTL)
		return nil
	}
	var raw [8]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return err
	}
	hexed := hex.EncodeToString(raw[:])
	display := hexed[0:4] + "-" + hexed[4:8] + "-" + hexed[8:12] + "-" + hexed[12:16]
	s.pairDisplay = display
	s.pairHash = sha256.Sum256([]byte(normalizePairing(display)))
	s.pairDeadline = time.Now().Add(pairingTTL)
	return nil
}

// PairingDisplay is the one-time code printed at serve start. It is not a
// durable credential and is consumed by RedeemPairing.
func (s *Server) PairingDisplay() string {
	s.pairMu.Lock()
	defer s.pairMu.Unlock()
	if s.pairConsumed || time.Now().After(s.pairDeadline) {
		return ""
	}
	return s.pairDisplay
}

func normalizePairing(code string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(strings.TrimSpace(code)) {
		if r == '-' || r == ' ' {
			continue
		}
		b.WriteRune(r)
	}
	return b.String()
}

// RedeemPairing exchanges the bootstrap code for a time-limited admin session.
func (s *Server) RedeemPairing(code string) (string, error) {
	s.pairMu.Lock()
	defer s.pairMu.Unlock()
	if s.pairConsumed {
		return "", errors.New("pairing code already used")
	}
	if time.Now().After(s.pairDeadline) {
		return "", errors.New("pairing code expired")
	}
	if s.pairAttempts >= pairingMaxAttempts {
		return "", errors.New("pairing attempts exceeded")
	}
	s.pairAttempts++
	got := sha256.Sum256([]byte(normalizePairing(code)))
	if subtle.ConstantTimeCompare(got[:], s.pairHash[:]) != 1 {
		return "", errors.New("pairing code rejected")
	}
	session, err := newSessionToken()
	if err != nil {
		return "", err
	}
	s.pairConsumed = true
	s.pairDisplay = ""
	s.sessMu.Lock()
	s.sessions[session] = time.Now().Add(adminSessionTTL)
	s.sessMu.Unlock()
	return session, nil
}

func newSessionToken() (string, error) {
	var raw [32]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(raw[:]), nil
}

func (s *Server) validAdminSession(tok string) bool {
	if tok == "" {
		return false
	}
	s.sessMu.Lock()
	defer s.sessMu.Unlock()
	exp, ok := s.sessions[tok]
	if !ok {
		return false
	}
	if time.Now().After(exp) {
		delete(s.sessions, tok)
		return false
	}
	return true
}

func (s *Server) listenPort() int {
	if s.d.ListenPort > 0 && s.d.ListenPort <= 65535 {
		return s.d.ListenPort
	}
	return 47611
}

func (s *Server) allowedHost(hostHeader string) bool {
	name, port, err := splitHTTPHost(hostHeader)
	if err != nil {
		return false
	}
	if port != fmt.Sprintf("%d", s.listenPort()) {
		return false
	}
	switch name {
	case "127.0.0.1", "localhost", "::1":
		return true
	default:
		return false
	}
}

func splitHTTPHost(host string) (name, port string, err error) {
	host = strings.TrimSpace(host)
	if host == "" || strings.ContainsAny(host, "/@ \\") {
		return "", "", errors.New("invalid host")
	}
	h, p, err := net.SplitHostPort(host)
	if err != nil {
		return "", "", err
	}
	h = strings.TrimSuffix(strings.ToLower(h), ".")
	if strings.HasPrefix(h, "[") && strings.HasSuffix(h, "]") {
		h = strings.TrimSuffix(strings.TrimPrefix(h, "["), "]")
	}
	if h == "" || p == "" {
		return "", "", errors.New("invalid host")
	}
	return h, p, nil
}

func (s *Server) allowedOrigin(origin string) bool {
	u, err := url.Parse(origin)
	if err != nil || u.Scheme != "http" || u.User != nil || u.Path != "" && u.Path != "/" || u.RawQuery != "" || u.Fragment != "" {
		return false
	}
	return s.allowedHost(u.Host)
}

func (s *Server) rejectBadOrigin(w http.ResponseWriter, r *http.Request) bool {
	site := strings.ToLower(strings.TrimSpace(r.Header.Get("Sec-Fetch-Site")))
	if site == "cross-site" && r.Method != http.MethodGet && r.Method != http.MethodHead {
		writeJSON(w, 403, map[string]any{"error": "cross-site request refused"})
		return true
	}
	origin := strings.TrimSpace(r.Header.Get("Origin"))
	if origin == "" {
		return false
	}
	if origin == "null" || !s.allowedOrigin(origin) {
		writeJSON(w, 403, map[string]any{"error": "origin not allowed"})
		return true
	}
	return false
}

func isDecisionPath(path string) bool {
	return path == "/v1/decide" || path == "/v1/observe"
}

func (s *Server) auth(next http.HandlerFunc, caps ...capability) http.HandlerFunc {
	need := capAdmin
	if len(caps) == 1 {
		need = caps[0]
	}
	return func(w http.ResponseWriter, r *http.Request) {
		h := r.Header.Get("Authorization")
		if !strings.HasPrefix(h, "Bearer ") {
			writeJSON(w, 401, map[string]any{"error": "unauthorized"})
			return
		}
		presented := strings.TrimPrefix(h, "Bearer ")
		switch need {
		case capDecision:
			if subtle.ConstantTimeCompare([]byte(presented), []byte(s.d.Token)) != 1 {
				writeJSON(w, 401, map[string]any{"error": "unauthorized"})
				return
			}
		default:
			if s.validAdminSession(presented) {
				break
			}
			if subtle.ConstantTimeCompare([]byte(presented), []byte(s.d.Token)) == 1 {
				writeJSON(w, 403, map[string]any{"error": "decision credential cannot call admin endpoints"})
				return
			}
			writeJSON(w, 401, map[string]any{"error": "unauthorized"})
			return
		}
		next(w, r)
	}
}

func (s *Server) pair(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	var body struct {
		Code string `json:"code"`
	}
	if err := readJSON(r, &body, 4<<10); err != nil || strings.TrimSpace(body.Code) == "" {
		writeJSON(w, 400, map[string]any{"error": "code required"})
		return
	}
	session, err := s.RedeemPairing(body.Code)
	if err != nil {
		writeJSON(w, 401, map[string]any{"error": err.Error()})
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, 200, map[string]any{
		"session":    session,
		"expires_in": int(adminSessionTTL.Seconds()),
		"scope":      "admin",
	})
}
