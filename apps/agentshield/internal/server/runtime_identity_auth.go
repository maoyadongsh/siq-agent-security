package server

import (
	"bytes"
	"crypto/subtle"
	"encoding/json"
	"io"
	"net/http"
	"strings"
)

func decisionTuple(raw []byte) (platform, agent, session string, ok bool) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	tok, err := dec.Token()
	if err != nil || tok != json.Delim('{') {
		return
	}
	seen := map[string]bool{}
	for dec.More() {
		key, e := dec.Token()
		if e != nil {
			return
		}
		name, yes := key.(string)
		if !yes {
			return
		}
		var value json.RawMessage
		if dec.Decode(&value) != nil {
			return
		}
		for _, field := range []string{"platform", "agent_id", "session_id"} {
			if strings.EqualFold(name, field) {
				if name != field || seen[field] {
					return
				}
				seen[field] = true
				var str string
				if json.Unmarshal(value, &str) != nil || bytes.Equal(value, []byte("null")) {
					return
				}
				switch field {
				case "platform":
					platform = str
				case "agent_id":
					agent = str
				case "session_id":
					session = str
				}
			}
		}
	}
	if _, err = dec.Token(); err != nil {
		return
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		return
	}
	ok = true
	return
}
func (s *Server) authorizeDecision(w http.ResponseWriter, r *http.Request, credential string) bool {
	global := subtle.ConstantTimeCompare([]byte(credential), []byte(s.d.Token)) == 1
	// Preserve the legacy handler's method error for authenticated old clients.
	if r.Method != http.MethodPost && global {
		return true
	}
	if !global {
		valid := false
		if strings.HasPrefix(credential, "ri-") {
			_, e := s.runtimeIdentities.Authenticate(credential)
			valid = e == nil
		} else if s.runtimeChecks != nil {
			valid = s.runtimeChecks.HasDecisionCredential(credential)
		}
		if !valid {
			writeJSON(w, 401, map[string]string{"error": "unauthorized"})
			return false
		}
	}
	limit := int64(1 << 20)
	if global {
		limit = 4 << 20
	}
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, limit))
	if err != nil {
		writeJSON(w, 400, map[string]string{"error": "invalid decision request"})
		return false
	}

	platform, agent, session, ok := decisionTuple(raw)
	if !ok {
		writeJSON(w, 400, map[string]string{"error": "invalid decision identity"})
		return false
	}
	r.Body = io.NopCloser(bytes.NewReader(raw))
	if global {
		if strings.HasPrefix(agent, "hri-") || strings.HasPrefix(agent, "rca-") {
			writeJSON(w, 403, map[string]string{"error": "scoped_decision_credential_required"})
			return false
		}
		return true
	}
	if strings.HasPrefix(credential, "ri-") {
		if _, err = s.runtimeIdentities.AuthorizeSession(credential, platform, agent, session); err == nil {
			return true
		}
	} else if s.runtimeChecks != nil && s.runtimeChecks.AuthorizeDecision(credential, platform, agent, session) {
		return true
	}
	writeJSON(w, 401, map[string]string{"error": "scoped_decision_credential_required"})
	return false
}
