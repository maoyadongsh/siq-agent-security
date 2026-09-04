// Package server exposes the decision API (dev-spec §3.8.1) over loopback HTTP
// with a bearer token. It holds no policy logic of its own: every decision is
// delegated to receipt.Engine, admissions to admission.Admit and grants to the
// grant state machine. Handlers never log request bodies.
package server

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/inventory"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

// Deps wires the server.
type Deps struct {
	Store   *state.Store
	Engine  *receipt.Engine
	Chain   *receipt.Chain
	Pack    *rulepack.Pack
	Key     *signing.Key
	Token   string
	Version string
	Mode    string
	UI      http.Handler // optional embedded console
}

// Server is the HTTP handler set.
type Server struct {
	d   Deps
	mux *http.ServeMux
}

// New builds the handler.
func New(d Deps) (*Server, error) {
	if d.Store == nil || d.Engine == nil || d.Chain == nil || d.Pack == nil || d.Key == nil || len(d.Token) < 32 {
		return nil, errors.New("server: incomplete dependencies")
	}
	s := &Server{d: d, mux: http.NewServeMux()}
	s.mux.HandleFunc("/v1/status", s.auth(s.status))
	s.mux.HandleFunc("/v1/decide", s.auth(s.decide))
	s.mux.HandleFunc("/v1/observe", s.auth(s.observe))
	s.mux.HandleFunc("/v1/hold/", s.auth(s.hold))
	s.mux.HandleFunc("/v1/receipts", s.auth(s.receipts))
	s.mux.HandleFunc("/v1/admit", s.auth(s.admit))
	s.mux.HandleFunc("/v1/admissions", s.auth(s.admissions))
	s.mux.HandleFunc("/v1/inventory", s.auth(s.inventory))
	s.mux.HandleFunc("/v1/grants", s.auth(s.grants))
	s.mux.HandleFunc("/v1/grants/", s.auth(s.grantAction))
	if d.UI != nil {
		s.mux.Handle("/", d.UI)
	} else {
		s.mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "text/plain; charset=utf-8")
			fmt.Fprintf(w, "agentshield %s — local mode · single user · %s\nAPI: /v1/status (bearer token required)\n", d.Version, d.Mode)
		})
	}
	return s, nil
}

// Handler returns the http.Handler (loopback check + mux).
func (s *Server) Handler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host, _, err := net.SplitHostPort(r.RemoteAddr)
		if err != nil || !isLoopback(host) {
			http.Error(w, "loopback only", http.StatusForbidden)
			return
		}
		s.mux.ServeHTTP(w, r)
	})
}

func isLoopback(host string) bool {
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func (s *Server) auth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		h := r.Header.Get("Authorization")
		if !strings.HasPrefix(h, "Bearer ") || subtle.ConstantTimeCompare([]byte(strings.TrimPrefix(h, "Bearer ")), []byte(s.d.Token)) != 1 {
			writeJSON(w, http.StatusUnauthorized, map[string]any{"error": "unauthorized"})
			return
		}
		next(w, r)
	}
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func readJSON(r *http.Request, v any, limit int64) error {
	dec := json.NewDecoder(http.MaxBytesReader(nil, r.Body, limit))
	dec.UseNumber()
	return dec.Decode(v)
}

func (s *Server) status(w http.ResponseWriter, r *http.Request) {
	seq, head := s.d.Chain.Head()
	writeJSON(w, 200, map[string]any{
		"version": s.d.Version, "enforcement_mode": s.d.Mode, "local_mode": true, "single_user": true,
		"rulepack_version": s.d.Pack.Version, "rulepack_source": s.d.Pack.Source,
		"chain":              map[string]any{"id": "local", "head_seq": seq, "head_hash": head},
		"signing_public_key": s.d.Key.PublicBase64(),
	})
}

func (s *Server) decide(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	var req receipt.Request
	if err := readJSON(r, &req, 4<<20); err != nil || req.Tool == "" || req.SessionID == "" || req.Platform == "" {
		writeJSON(w, 400, map[string]any{"error": "invalid request: platform, session_id and tool are required"})
		return
	}
	d, err := s.d.Engine.Decide(req)
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "decision failed"})
		return
	}
	resp := map[string]any{"action": d.Action, "reason": d.Reason, "receipt_id": d.Receipt.ReceiptID}
	if d.Params != nil {
		resp["params"] = d.Params
	}
	if d.Hold != nil {
		resp["hold"] = d.Hold
	}
	writeJSON(w, 200, resp)
}

func (s *Server) observe(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	var body struct {
		receipt.Request
		Result string `json:"result"`
	}
	if err := readJSON(r, &body, 4<<20); err != nil || body.Tool == "" || body.SessionID == "" {
		writeJSON(w, 400, map[string]any{"error": "invalid request"})
		return
	}
	if len(body.Result) > 64<<10 {
		body.Result = body.Result[:64<<10]
	}
	rec, err := s.d.Engine.Observe(body.Request, body.Result)
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "observe failed"})
		return
	}
	writeJSON(w, 200, map[string]any{"receipt_id": rec.ReceiptID, "taint_labels": rec.TaintLabels})
}

func (s *Server) hold(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/v1/hold/")
	var body struct {
		Approve bool   `json:"approve"`
		ActorID string `json:"actor_id"`
	}
	if err := readJSON(r, &body, 64<<10); err != nil || body.ActorID == "" {
		writeJSON(w, 400, map[string]any{"error": "actor_id required"})
		return
	}
	all, err := s.d.Chain.Read()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "chain unreadable"})
		return
	}
	for i := len(all) - 1; i >= 0; i-- {
		if all[i].ReceiptID == id && all[i].Action == receipt.ActionHold {
			rec, err := s.d.Engine.ResolveHold(all[i], body.Approve, body.ActorID)
			if err != nil {
				writeJSON(w, 400, map[string]any{"error": err.Error()})
				return
			}
			writeJSON(w, 200, map[string]any{"receipt_id": rec.ReceiptID, "action": rec.Action})
			return
		}
	}
	writeJSON(w, 404, map[string]any{"error": "held receipt not found"})
}

func (s *Server) receipts(w http.ResponseWriter, r *http.Request) {
	all, err := s.d.Chain.Read()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "chain unreadable"})
		return
	}
	since := -1
	if q := r.URL.Query().Get("since_seq"); q != "" {
		fmt.Sscanf(q, "%d", &since)
	}
	out := make([]receipt.Receipt, 0)
	for _, rc := range all {
		if rc.Seq > since {
			out = append(out, rc)
		}
		if len(out) >= 500 {
			break
		}
	}
	verified := receipt.Verify(all, s.d.Key.Public()) == nil
	writeJSON(w, 200, map[string]any{"receipts": out, "verified": verified})
}

func (s *Server) admit(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	var body struct {
		Path       string `json:"path"`
		TrustLevel string `json:"trust_level"`
	}
	if err := readJSON(r, &body, 64<<10); err != nil || body.Path == "" {
		writeJSON(w, 400, map[string]any{"error": "path required"})
		return
	}
	if body.TrustLevel == "" {
		body.TrustLevel = "unknown"
	}
	if st, err := os.Stat(body.Path); err != nil || !st.IsDir() {
		writeJSON(w, 400, map[string]any{"error": "path is not a readable directory"})
		return
	}
	res, err := admission.Admit(body.Path, admission.Options{
		Source:  admission.Source{Type: "local_dir", Locator: body.Path, TrustLevel: body.TrustLevel},
		Version: s.d.Version, Key: s.d.Key, Pack: s.d.Pack,
	})
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "admission failed"})
		return
	}
	if err := s.d.Store.PutAdmission(res); err != nil {
		writeJSON(w, 500, map[string]any{"error": "store failed"})
		return
	}
	writeJSON(w, 200, map[string]any{"admission": res.Admission, "skill_card": res.SkillCard})
}

func (s *Server) inventory(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	var body struct {
		Cwd string `json:"cwd"`
	}
	_ = readJSON(r, &body, 64<<10)
	admissions, _ := s.d.Store.ListAdmissions()
	byHash := map[string]string{}
	for _, a := range admissions {
		byHash[a.ContentHash] = a.Verdict
	}
	rep, err := inventory.Run(inventory.Options{Cwd: body.Cwd, Version: s.d.Version, Key: s.d.Key,
		HasAdmission: func(h string) (string, bool) { v, ok := byHash[h]; return v, ok }})
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "inventory failed"})
		return
	}
	writeJSON(w, 200, rep)
}

func (s *Server) admissions(w http.ResponseWriter, r *http.Request) {
	list, err := s.d.Store.ListAdmissions()
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": "store unreadable"})
		return
	}
	writeJSON(w, 200, map[string]any{"admissions": list})
}

// grants: GET list; POST create from admission.
func (s *Server) grants(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		list, err := s.d.Store.ListGrants()
		if err != nil {
			writeJSON(w, 500, map[string]any{"error": "store unreadable"})
			return
		}
		writeJSON(w, 200, map[string]any{"grants": list})
	case http.MethodPost:
		var body struct {
			AdmissionID string `json:"admission_id"`
			Platform    string `json:"platform"`
			SubjectType string `json:"subject_type"`
			SubjectID   string `json:"subject_id"`
			Redact      bool   `json:"redact_secrets"`
		}
		if err := readJSON(r, &body, 64<<10); err != nil || body.AdmissionID == "" || body.Platform == "" || body.SubjectID == "" {
			writeJSON(w, 400, map[string]any{"error": "admission_id, platform, subject_id required"})
			return
		}
		if body.SubjectType == "" {
			body.SubjectType = "agent_instance"
		}
		adm, err := s.d.Store.GetAdmission(body.AdmissionID)
		if err != nil {
			writeJSON(w, 404, map[string]any{"error": "admission not found"})
			return
		}
		res, err := grant.Build(*adm, grant.Options{Subject: grant.Subject{Type: body.SubjectType, ID: body.SubjectID},
			Platform: body.Platform, EnforcementMode: s.d.Mode, Key: s.d.Key, RedactSecrets: body.Redact})
		if err != nil {
			writeJSON(w, 400, map[string]any{"error": err.Error()})
			return
		}
		if err := s.d.Store.PutGrant(res.Grant); err != nil {
			writeJSON(w, 500, map[string]any{"error": "store failed"})
			return
		}
		_ = s.d.Store.PutDesiredPolicy(res.DesiredPolicy)
		writeJSON(w, 200, map[string]any{"grant": res.Grant, "desired_policy": res.DesiredPolicy})
	default:
		writeJSON(w, 405, map[string]any{"error": "GET or POST"})
	}
}

// grantAction: POST /v1/grants/{id}/{approve|reject|deploy|revoke|resolve-overlap|effective}
func (s *Server) grantAction(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "POST required"})
		return
	}
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v1/grants/"), "/")
	if len(parts) != 2 {
		writeJSON(w, 404, map[string]any{"error": "not found"})
		return
	}
	g, err := s.d.Store.GetGrant(parts[0])
	if err != nil {
		writeJSON(w, 404, map[string]any{"error": "grant not found"})
		return
	}
	var body struct {
		ActorID  string                 `json:"actor_id"`
		Channel  string                 `json:"channel"`
		Index    int                    `json:"index"`
		Readback *grant.Readback        `json:"readback"`
		Facts    map[string]string      `json:"fact_readbacks"`
		Extra    map[string]interface{} `json:"-"`
	}
	_ = readJSON(r, &body, 64<<10)
	actor := grant.Approval{ActorType: "human", ActorID: body.ActorID, ApprovedAt: time.Now().UTC().Format(time.RFC3339), Channel: body.Channel}
	if actor.Channel == "" {
		actor.Channel = "console"
	}
	var out grant.Grant
	switch parts[1] {
	case "approve":
		out, err = grant.Approve(*g, actor, s.d.Key)
	case "reject":
		out, err = grant.Reject(*g, s.d.Key)
	case "revoke":
		out, err = grant.Revoke(*g, s.d.Key)
	case "deploy":
		out, err = grant.MarkDeployed(*g, s.d.Key)
	case "resolve-overlap":
		out, err = grant.ResolveOverlap(*g, body.Index, actor, s.d.Key)
	case "effective":
		if body.Readback == nil {
			err = errors.New("readback required")
		} else {
			out, err = grant.MarkEffective(*g, *body.Readback, body.Facts, s.d.Key)
		}
	default:
		writeJSON(w, 404, map[string]any{"error": "unknown action"})
		return
	}
	if err != nil {
		writeJSON(w, 400, map[string]any{"error": err.Error()})
		return
	}
	if err := s.d.Store.PutGrant(out); err != nil {
		writeJSON(w, 500, map[string]any{"error": "store failed"})
		return
	}
	writeJSON(w, 200, map[string]any{"grant": out})
}
